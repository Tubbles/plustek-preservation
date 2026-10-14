"""Tests for eeprom_read.py against a simulated scanner, no USB needed.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import argparse
import contextlib
import io
import json
import pathlib
import struct
import sys
import tempfile
import types
import unittest

if "usb.core" not in sys.modules:
    usb_stub = types.ModuleType("usb")
    usb_core_stub = types.ModuleType("usb.core")
    setattr(usb_core_stub, "USBError", type("USBError", (Exception,), {}))
    setattr(usb_stub, "core", usb_core_stub)
    sys.modules["usb"] = usb_stub
    sys.modules["usb.core"] = usb_core_stub

import usb.core

import eeprom_read

PLIST_0A = 0x40  # the OpticFilm 120 plist value 0x48 with EPROMSEL clear
FORBIDDEN_COMMANDS = [value for value in range(256) if value != 0x00 and not 0x80 <= value <= 0xBF]


def patterned_words() -> list:
    """64 distinct words, none 0x0000 or 0xffff."""
    return [0x1000 + 0x0101 * address for address in range(64)]


def words_of(image: bytes) -> list:
    return list(struct.unpack(f"<{len(image) // 2}H", image))


class Fake93C46:
    """A 93C46 in x16 organisation: write-disabled at power-up, READ independent of EWEN.

    EWEN is modelled (it latches write_enabled) so that tests can assert it
    never arrives. WRITE, ERASE, ERAL and WRAL raise at once.
    """

    def __init__(self, words):
        self.words = list(words)
        self.write_enabled = False
        self.ewen_received = False

    def command(self, value: int):
        """Return the word clocked out, or None for a command without data."""
        opcode, address = value >> 6, value & 0x3F
        if opcode == 0b10:
            return self.words[address]
        if opcode == 0b00 and address >> 4 == 0b00:
            self.write_enabled = False
            return None
        if opcode == 0b00 and address >> 4 == 0b11:
            self.write_enabled = self.ewen_received = True
            return None
        raise AssertionError(f"forbidden 93C46 command 0x{value:02x}")


class FakeScanner:
    """Accepts exactly the register requests eeprom_read may send, with the Windows framing.

    data_source: "eeprom" (the Fake93C46), "stuck_high", "stuck_low" or
    "constant" (the data registers ignore the command, as exposure
    registers would). read_0a: a fixed value every read of 0x0a returns
    (pin levels instead of the latch). failing_write: (register, value)
    of a write that raises USBError once, after taking effect when
    failing_write_applied is set.
    """

    def __init__(self, words=None, register_0a=PLIST_0A, data_source="eeprom", busy_polls=0, busy_forever=False,
                 short_read_register=None, missing_acknowledge_register=None, short_write=False,
                 failing_transfer=None, disconnect_after=None, changed_word_on_second_read=None,
                 read_0a=None, failing_write=None, failing_write_applied=False):
        self.eeprom = Fake93C46(words if words is not None else patterned_words())
        self.registers = {0x0A: register_0a, 0x31: 0xBC, 0x34: 0x00, 0x4F: 0x03, 0x8E: 0x55, 0x8F: 0x00}
        self.power_on_0a = register_0a
        self.data_source = data_source
        self.busy_polls = busy_polls
        self.busy_left = 0
        self.busy_forever = busy_forever
        self.short_read_register = short_read_register
        self.missing_acknowledge_register = missing_acknowledge_register
        self.short_write = short_write
        self.failing_transfer = failing_transfer
        self.disconnect_after = disconnect_after
        self.changed_word_on_second_read = changed_word_on_second_read
        self.read_0a = read_0a
        self.failing_write = failing_write
        self.failing_write_applied = failing_write_applied
        self.reads_per_address = {}
        self.transfers = 0
        self.writes = []
        self.reads = []

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        self.transfers += 1
        if self.disconnect_after is not None and self.transfers > self.disconnect_after:
            raise usb.core.USBError("No such device (it may have been disconnected)")
        if self.transfers == self.failing_transfer:
            raise usb.core.USBError("Pipe error")
        if request != 0x04:
            raise AssertionError(f"bRequest 0x{request:02x}")
        if request_type == 0x40:
            if value != 0x0083 or index != 0 or len(data_or_length) != 2:
                raise AssertionError(f"unexpected OUT wValue 0x{value:04x} wIndex 0x{index:04x}")
            return self.handle_write(*bytes(data_or_length))
        if request_type == 0xC0:
            if value != 0x008E or index & 0xFF != 0x22 or data_or_length != 2:
                raise AssertionError(f"unexpected IN wValue 0x{value:04x} wIndex 0x{index:04x}")
            return self.handle_read(index >> 8)
        raise AssertionError(f"unexpected bmRequestType 0x{request_type:02x}")

    def handle_write(self, register, value):
        self.writes.append((register, value))
        failing = (register, value) == self.failing_write
        if failing:
            self.failing_write = None
            if not self.failing_write_applied:
                raise usb.core.USBError("Pipe error")
        if register == 0x0A:
            self.write_0a(value)
        elif register == 0x8B:
            if not self.registers[0x0A] & 0x08:
                raise AssertionError("command sent with EPROMSEL clear")
            self.run_command(value)
        else:
            raise AssertionError(f"write to register 0x{register:02x}")
        if failing:
            raise usb.core.USBError("Pipe error")
        return 1 if self.short_write else 2

    def write_0a(self, value):
        """Only EPROMSEL may differ from the power-on value. An unchanged value is the restore after a lost write."""
        if (value ^ self.power_on_0a) & ~0x08 or (value ^ self.registers[0x0A]) not in (0x00, 0x08):
            raise AssertionError(f"0x0a write 0x{value:02x} changes more than EPROMSEL")
        self.registers[0x0A] = value

    def run_command(self, value):
        word = self.eeprom.command(value)
        self.busy_left = self.busy_polls
        if word is None or self.data_source == "constant":
            return
        if self.data_source == "stuck_high":
            word = 0xFFFF
        elif self.data_source == "stuck_low":
            word = 0x0000
        address = value & 0x3F
        self.reads_per_address[address] = self.reads_per_address.get(address, 0) + 1
        if address == self.changed_word_on_second_read and self.reads_per_address[address] == 2:
            word ^= 0x0100
        self.registers[0x8F], self.registers[0x8E] = word & 0xFF, word >> 8

    def handle_read(self, register):
        if register not in (0x0A, 0x31, 0x34, 0x4F, 0x8E, 0x8F):
            raise AssertionError(f"read of register 0x{register:02x}")
        self.reads.append(register)
        value = self.registers[register]
        if register == 0x4F:
            value = self.busy_value()
        if register == 0x0A and self.read_0a is not None:
            value = self.read_0a
        reply = bytes([value, 0x00 if register == self.missing_acknowledge_register else 0x55])
        return reply[:1] if register == self.short_read_register else reply

    def busy_value(self):
        if self.busy_forever or self.busy_left > 0:
            self.busy_left -= 1
            return 0x13
        return 0x03


def run_read(scanner, word_count=eeprom_read.DEFAULT_WORD_COUNT):
    """Run run() in a temporary directory. Return the exit code, both pass files and the log records.

    Fails when the run sent EWEN, whatever the test checks otherwise.
    """
    with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
        log_file = io.StringIO()
        session = eeprom_read.Session(scanner, log_file, sleep=lambda seconds: None)
        exit_code = eeprom_read.run(session, pathlib.Path(directory), word_count)
        images = [path.read_bytes() if path.exists() else None
                  for path in (pathlib.Path(directory) / "pass1.bin", pathlib.Path(directory) / "pass2.bin")]
    if scanner.eeprom.ewen_received:
        raise AssertionError("the run sent EWEN")
    records = [json.loads(line) for line in log_file.getvalue().splitlines()]
    return exit_code, images, records


def records_of_kind(records, kind):
    return [record for record in records if record["kind"] == kind]


def commands_sent(scanner):
    return [value for register, value in scanner.writes if register == 0x8B]


class ReadTests(unittest.TestCase):
    def test_good_eeprom_gives_identical_passes_and_exit_zero(self):
        for word_count in (8, 64):
            with self.subTest(word_count=word_count):
                exit_code, images, records = run_read(FakeScanner(), word_count)
                self.assertEqual(exit_code, eeprom_read.EXIT_GOOD)
                self.assertEqual(words_of(images[0]), patterned_words()[:word_count])
                self.assertEqual(images[0], images[1])
                self.assertEqual(records_of_kind(records, "hex_dump")[0]["lines"][0],
                                 "00: " + images[0][:16].hex(" "))
                self.assertTrue(records_of_kind(records, "address_dependence")[0]["follows_address"])

    def test_default_run_reads_words_0_to_7_in_the_vendor_order(self):
        scanner = FakeScanner()
        run_read(scanner)
        self.assertEqual(commands_sent(scanner), list(range(0x80, 0x88)) + list(range(0x87, 0x7F, -1)) + [0x00])
        self.assertEqual([value for register, value in scanner.writes if register == 0x0A], [0x48, 0x40])
        self.assertEqual(scanner.registers[0x0A], PLIST_0A)
        word_reads = [register for register in scanner.reads if register in (0x8E, 0x8F)][2:]
        self.assertEqual(word_reads, [0x8F, 0x8E] * 16)

    def test_every_0x0a_write_is_read_back(self):
        scanner = FakeScanner()
        run_read(scanner)
        self.assertEqual(scanner.reads.count(0x0A), 3)

    def test_identity_bytes_are_reported(self):
        image = (b"\xb3\x07\x06\x14" + "Film Scanner".encode("utf-16-le")
                 + struct.pack("<50H", *range(0x2000, 0x2032)))
        exit_code, _, records = run_read(FakeScanner(words=words_of(image)), 64)
        self.assertEqual(exit_code, eeprom_read.EXIT_GOOD)
        search = records_of_kind(records, "identity_search")[0]
        self.assertTrue(search["vid_pid_le"])
        self.assertTrue(search["film_scanner_utf16le"])
        self.assertFalse(search["vid_pid_le_bytes_swapped"])

    def test_identity_bytes_with_swapped_bytes_are_reported(self):
        image = eeprom_read.byte_swapped(b"\xb3\x07\x06\x14" + struct.pack("<62H", *range(0x2000, 0x203E)))
        _, _, records = run_read(FakeScanner(words=words_of(image)))
        search = records_of_kind(records, "identity_search")[0]
        self.assertFalse(search["vid_pid_le"])
        self.assertTrue(search["vid_pid_le_bytes_swapped"])

    def test_blank_eeprom_is_uniform(self):
        exit_code, images, records = run_read(FakeScanner(words=[0xFFFF] * 64))
        self.assertEqual(exit_code, eeprom_read.EXIT_UNIFORM)
        self.assertEqual(images, [b"\xff" * 16, b"\xff" * 16])
        self.assertEqual(records_of_kind(records, "uniform_image")[0]["word"], "ffff")

    def test_no_chip_or_stuck_data_is_uniform(self):
        for data_source, word in (("stuck_high", "ffff"), ("stuck_low", "0000"), ("constant", "5500")):
            with self.subTest(data_source=data_source):
                exit_code, _, records = run_read(FakeScanner(data_source=data_source))
                self.assertEqual(exit_code, eeprom_read.EXIT_UNIFORM)
                self.assertEqual(records_of_kind(records, "uniform_image")[0]["word"], word)

    def test_data_registers_that_ignore_the_address_are_named(self):
        _, _, records = run_read(FakeScanner(data_source="constant"))
        dependence = records_of_kind(records, "address_dependence")[0]
        self.assertFalse(dependence["follows_address"])
        self.assertEqual((dependence["distinct_low_0x8f"], dependence["distinct_high_0x8e"]), (1, 1))
        self.assertIn("EXPG", dependence["note"])

    def test_differing_passes_are_reported(self):
        exit_code, images, records = run_read(FakeScanner(changed_word_on_second_read=5))
        self.assertEqual(exit_code, eeprom_read.EXIT_PASSES_DIFFER)
        self.assertEqual(records_of_kind(records, "compare")[0]["differing_words"], ["05"])
        self.assertNotEqual(images[0], images[1])

    def test_short_busy_periods_are_waited_out(self):
        scanner = FakeScanner(busy_polls=3)
        self.assertEqual(run_read(scanner)[0], eeprom_read.EXIT_GOOD)

    def test_busy_timeout_is_bounded_and_restores_0x0a(self):
        scanner = FakeScanner(busy_forever=True)
        exit_code, _, records = run_read(scanner)
        self.assertEqual(exit_code, eeprom_read.EXIT_BUSY_TIMEOUT)
        self.assertEqual(scanner.reads.count(0x4F), 1 + eeprom_read.BUSY_POLL_LIMIT)
        self.assertEqual(scanner.registers[0x0A], PLIST_0A)
        self.assertEqual(records_of_kind(records, "epromsel")[-1]["action"], "restored")

    def test_short_reads_are_errors(self):
        for register in (0x8F, 0x8E, 0x4F, 0x0A):
            with self.subTest(register=register):
                scanner = FakeScanner(short_read_register=register)
                self.assertEqual(run_read(scanner)[0], eeprom_read.EXIT_USB_ERROR)

    def test_missing_0x55_is_an_error(self):
        for register in (0x8F, 0x8E, 0x4F, 0x0A, 0x31):
            with self.subTest(register=register):
                scanner = FakeScanner(missing_acknowledge_register=register)
                self.assertEqual(run_read(scanner)[0], eeprom_read.EXIT_USB_ERROR)

    def test_short_write_is_an_error(self):
        scanner = FakeScanner(short_write=True)
        self.assertEqual(run_read(scanner)[0], eeprom_read.EXIT_USB_ERROR)

    def test_0x0a_is_restored_after_an_error(self):
        for failing_transfer in (13, 45, 70):
            with self.subTest(failing_transfer=failing_transfer):
                scanner = FakeScanner(failing_transfer=failing_transfer)
                exit_code, _, records = run_read(scanner)
                self.assertEqual(exit_code, eeprom_read.EXIT_USB_ERROR)
                self.assertEqual(scanner.registers[0x0A], PLIST_0A)
                self.assertEqual(scanner.writes[-1], (0x0A, PLIST_0A))
                self.assertEqual(records_of_kind(records, "epromsel")[-1]["action"], "restored")

    def test_failed_select_write_is_restored(self):
        for applied in (False, True):
            with self.subTest(write_reached_the_chip=applied):
                scanner = FakeScanner(failing_write=(0x0A, 0x48), failing_write_applied=applied)
                exit_code, _, records = run_read(scanner)
                self.assertEqual(exit_code, eeprom_read.EXIT_USB_ERROR)
                self.assertEqual([value for register, value in scanner.writes if register == 0x0A], [0x48, 0x40])
                self.assertEqual(commands_sent(scanner), [])
                self.assertEqual(scanner.registers[0x0A], PLIST_0A)
                self.assertEqual(records_of_kind(records, "epromsel")[-1]["action"], "restored")

    def test_0x0a_read_back_mismatch_stops_before_any_command(self):
        scanner = FakeScanner(read_0a=PLIST_0A)
        exit_code, _, records = run_read(scanner)
        self.assertEqual(exit_code, eeprom_read.EXIT_READBACK)
        self.assertEqual(commands_sent(scanner), [])
        self.assertEqual([value for register, value in scanner.writes if register == 0x0A], [0x48, 0x40])
        self.assertEqual(scanner.registers[0x0A], PLIST_0A)
        self.assertEqual(records_of_kind(records, "epromsel")[-1]["action"], "restored")

    def test_failed_restore_after_a_disconnect_is_logged(self):
        scanner = FakeScanner(disconnect_after=40)
        exit_code, _, records = run_read(scanner)
        self.assertEqual(exit_code, eeprom_read.EXIT_USB_ERROR)
        self.assertEqual(records_of_kind(records, "epromsel")[-1]["action"], "restore failed")

    def test_epromsel_already_set_is_not_written(self):
        scanner = FakeScanner(register_0a=0x48)
        self.assertEqual(run_read(scanner)[0], eeprom_read.EXIT_GOOD)
        self.assertNotIn(0x0A, [register for register, _ in scanner.writes])

    def test_no_run_sends_ewen_or_a_write_opcode(self):
        scenarios = ((FakeScanner(), 8), (FakeScanner(), 64), (FakeScanner(busy_forever=True), 8),
                     (FakeScanner(failing_transfer=50), 64), (FakeScanner(words=[0xFFFF] * 64), 8),
                     (FakeScanner(changed_word_on_second_read=1), 8))
        for scanner, word_count in scenarios:
            run_read(scanner, word_count)
            self.assertTrue(set(commands_sent(scanner)) <= set(range(0x80, 0xC0)) | {0x00})
            self.assertFalse(scanner.eeprom.ewen_received)

    def test_the_fake_notices_ewen(self):
        scanner = FakeScanner(register_0a=0x48)
        scanner.handle_write(0x8B, 0x30)
        self.assertTrue(scanner.eeprom.ewen_received)


class WordCountTests(unittest.TestCase):
    def test_word_counts_outside_the_limits_are_refused_before_any_transfer(self):
        for word_count in (-1, 0, 1, 65, 128):
            with self.subTest(word_count=word_count):
                scanner = FakeScanner()
                self.assertEqual(run_read(scanner, word_count)[0], eeprom_read.EXIT_USB_ERROR)
                self.assertEqual(scanner.transfers, 0)

    def test_the_largest_word_count_reads_every_word(self):
        scanner = FakeScanner()
        run_read(scanner, 64)
        self.assertEqual(commands_sent(scanner), list(range(0x80, 0xC0)) + list(range(0xBF, 0x7F, -1)) + [0x00])

    def test_the_command_line_accepts_2_to_64(self):
        self.assertEqual(eeprom_read.word_count_argument("8"), 8)
        self.assertEqual(eeprom_read.word_count_argument("64"), 64)
        self.assertEqual(eeprom_read.word_count_argument("0x40"), 64)
        for text in ("1", "65", "0x41", "eight", ""):
            with self.subTest(text=text):
                with self.assertRaises(argparse.ArgumentTypeError):
                    eeprom_read.word_count_argument(text)

    def test_default_is_8(self):
        self.assertEqual(eeprom_read.DEFAULT_WORD_COUNT, 8)


class SafetyCheckTests(unittest.TestCase):
    def session(self, scanner, original_0a=PLIST_0A):
        session = eeprom_read.Session(scanner, io.StringIO(), sleep=lambda seconds: None)
        session.original_0a = session.current_0a = original_0a
        return session

    def test_only_read_and_ewds_pass_the_command_check(self):
        session = self.session(FakeScanner())
        for value in range(256):
            with self.subTest(value=value):
                if value in FORBIDDEN_COMMANDS:
                    with self.assertRaises(PermissionError):
                        eeprom_read.check_register_write(session, 0x8B, value)
                else:
                    eeprom_read.check_register_write(session, 0x8B, value)

    def test_forbidden_commands_never_reach_the_device(self):
        for value in FORBIDDEN_COMMANDS + [0x30, -1, 0x100]:
            with self.subTest(value=value):
                scanner = FakeScanner(register_0a=0x48)
                with self.assertRaises(PermissionError):
                    eeprom_read.write_register(self.session(scanner, 0x48), 0x8B, value)
                self.assertEqual(scanner.transfers, 0)

    def test_addresses_outside_the_chip_never_reach_the_device(self):
        for address in (64, 0x7F, 0x80, 0xFF, -1):
            with self.subTest(address=address):
                scanner = FakeScanner(register_0a=0x48)
                session = self.session(scanner, 0x48)
                with self.assertRaises(PermissionError):
                    eeprom_read.read_word(session, address)
                with self.assertRaises(PermissionError):
                    eeprom_read.read_pass(session, [address], io.BytesIO())
                self.assertEqual(scanner.transfers, 0)

    def test_other_registers_are_refused(self):
        session = self.session(FakeScanner())
        for register in (0x00, 0x01, 0x0B, 0x31, 0x4F, 0x8A, 0x8C, 0x8E, 0x8F, 0x101):
            with self.subTest(register=register):
                with self.assertRaises(PermissionError):
                    eeprom_read.check_register_write(session, register, 0)

    def test_0x0a_may_only_toggle_epromsel(self):
        session = self.session(FakeScanner())
        eeprom_read.check_register_write(session, 0x0A, PLIST_0A | 0x08)
        for value in (PLIST_0A, PLIST_0A | 0x18, 0x48 ^ 0x40, 0x00, 0xFF):
            with self.subTest(value=value):
                with self.assertRaises(PermissionError):
                    eeprom_read.check_register_write(session, 0x0A, value)
        session.current_0a = PLIST_0A | 0x08
        eeprom_read.check_register_write(session, 0x0A, PLIST_0A)

    def test_0x0a_write_before_reading_it_is_refused(self):
        session = eeprom_read.Session(FakeScanner(), io.StringIO())
        with self.assertRaises(PermissionError):
            eeprom_read.check_register_write(session, 0x0A, 0x48)

    def test_reads_outside_the_list_are_refused(self):
        scanner = FakeScanner()
        for register in (0x00, 0x8B, 0x8A, 0x101, 0x36):
            with self.subTest(register=register):
                with self.assertRaises(PermissionError):
                    eeprom_read.read_register(self.session(scanner), register)
        self.assertEqual(scanner.transfers, 0)


class ConflictingProcessTests(unittest.TestCase):
    def fake_proc(self, directory, command_lines):
        for pid, arguments in enumerate(command_lines, start=100):
            process = pathlib.Path(directory) / str(pid)
            process.mkdir()
            (process / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")

    def test_finds_the_watcher_started_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, [[b"sudo", b"/home/pi/plustek-preservation/venv/bin/python",
                                        b"/home/pi/plustek-preservation/probe_readonly.py", b"--watch", b"20"]])
            self.assertTrue(eeprom_read.conflicting_process_running(pathlib.Path(directory)))

    def test_finds_the_watcher_started_keep_awake(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, [[b"sudo", b"-n", b"/home/pi/plustek-preservation/venv/bin/python",
                                        b"/home/pi/plustek-preservation/keep_awake.py",
                                        b"/home/pi/scanner-log/keep-awake-20261014T120000Z.jsonl"]])
            self.assertTrue(eeprom_read.conflicting_process_running(pathlib.Path(directory)))

    def test_ignores_other_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, [[b"/bin/sh", b"./watch-scanner.sh"], [b"python", b"eeprom_read.py", b"out"]])
            self.assertFalse(eeprom_read.conflicting_process_running(pathlib.Path(directory)))


if __name__ == "__main__":
    unittest.main()
