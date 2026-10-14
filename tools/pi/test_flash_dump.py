"""Tests for flash_dump.py against a simulated scanner, no USB needed.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import contextlib
import io
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

import flash_dump

FLASH_SIZE = 512 * 1024
MACRONIX_512_KIB = bytes.fromhex("c22013")


def patterned_flash() -> bytes:
    """Every 64-byte block differs from every other one, and none is uniform."""
    return b"".join(struct.pack("<II", address, 0xA5A5A5A5) * 8 for address in range(0, FLASH_SIZE, 64))


def blank_start_flash() -> bytes:
    """Blank first 4 KiB, then the pattern: the address check at 0 and 0x40 sees only blank blocks."""
    return b"\xff" * 4096 + patterned_flash()[4096:]


def big_endian_24_of_first_bytes(address: int) -> int:
    low, middle, high = struct.pack("<I", address)[:3]
    return (low << 16) | (middle << 8) | high


class FakeScanner:
    """Answers exactly the vendor requests flash_dump may send, with the Windows framing.

    address_decoder maps the LE32 address the host writes to the flash
    offset the simulated ASIC reads from; None means the write is ignored.
    """

    def __init__(self, flash, jedec_id=MACRONIX_512_KIB, address_decoder=lambda address: address,
                 auto_increment=True, data_length=64, short_address_write=False, data_reads_before_disconnect=None):
        self.flash = flash
        self.jedec_id = jedec_id
        self.address_decoder = address_decoder
        self.auto_increment = auto_increment
        self.data_length = data_length
        self.short_address_write = short_address_write
        self.data_reads_left = data_reads_before_disconnect
        self.pointer = 0
        self.writes = []

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        length = len(data_or_length) if request_type == 0x40 else data_or_length
        if request != flash_dump.request_code_for(length):
            raise AssertionError(f"bRequest 0x{request:02x} for a {length}-byte transfer")
        if request_type == 0x40:
            return self.handle_write(value, index, bytes(data_or_length))
        if request_type == 0xC0:
            return self.handle_read(value, index)
        raise AssertionError(f"unexpected bmRequestType 0x{request_type:02x}")

    def handle_write(self, value, index, data):
        if value != flash_dump.FLASH_WRITE_VALUE:
            raise AssertionError(f"unexpected OUT wValue 0x{value:04x}")
        self.writes.append((index, data))
        if index != flash_dump.ADDRESS_INDEX:
            return len(data)
        if self.short_address_write:
            return len(data) - 1
        decoded = self.address_decoder(struct.unpack("<I", data)[0])
        if decoded is not None:
            self.pointer = decoded % len(self.flash)
        return len(data)

    def handle_read(self, value, index):
        if value == flash_dump.FLASH_READ_VALUE and index == flash_dump.JEDEC_ID_INDEX:
            return self.jedec_id
        if value == flash_dump.FLASH_READ_VALUE and index == flash_dump.DATA_INDEX:
            return self.read_data()
        if value == 0x008E and index == 0x0020:
            return b"\xaa"
        if value in (0x008E, 0x018E) and index & 0xFF == 0x22:
            return b"\x00\x55"
        raise AssertionError(f"unexpected IN wValue 0x{value:04x} wIndex 0x{index:04x}")

    def read_data(self):
        if self.data_reads_left is not None:
            if self.data_reads_left == 0:
                raise usb.core.USBError("No such device (it may have been disconnected)")
            self.data_reads_left -= 1
        block = self.flash[self.pointer:self.pointer + self.data_length]
        block += self.flash[:self.data_length - len(block)]
        if self.auto_increment:
            self.pointer = (self.pointer + 64) % len(self.flash)
        return block


def run_dump(scanner, id_only=False):
    """Run run() in a temporary directory; return the exit code, both pass files and the log."""
    with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
        log_file = io.StringIO()
        exit_code = flash_dump.run(flash_dump.Session(scanner, log_file), pathlib.Path(directory), id_only)
        images = [path.read_bytes() if path.exists() else None
                  for path in (pathlib.Path(directory) / "pass1.bin", pathlib.Path(directory) / "pass2.bin")]
    return exit_code, images, log_file.getvalue()


class DumpTests(unittest.TestCase):
    def test_good_flash_gives_identical_passes_and_exit_zero(self):
        flash = patterned_flash()
        exit_code, images, _ = run_dump(FakeScanner(flash))
        self.assertEqual(exit_code, flash_dump.EXIT_GOOD)
        self.assertEqual(images, [flash, flash])

    def test_mostly_blank_flash_with_one_record_is_good(self):
        flash = bytes(range(64)) + b"\xff" * (FLASH_SIZE - 64)
        exit_code, images, _ = run_dump(FakeScanner(flash))
        self.assertEqual(exit_code, flash_dump.EXIT_GOOD)
        self.assertEqual(images, [flash, flash])

    def test_every_write_passes_the_allowlist_for_the_decoded_size(self):
        scanner = FakeScanner(patterned_flash())
        run_dump(scanner)
        self.assertTrue(scanner.writes)
        for index, data in scanner.writes:
            flash_dump.check_write_allowed(index, data, FLASH_SIZE)

    def test_missing_auto_increment_still_dumps(self):
        flash = patterned_flash()
        exit_code, images, _ = run_dump(FakeScanner(flash, auto_increment=False))
        self.assertEqual(exit_code, flash_dump.EXIT_GOOD)
        self.assertEqual(images, [flash, flash])

    def test_uniform_images_are_reported(self):
        for value in (b"\xff", b"\x00"):
            with self.subTest(value=value):
                exit_code, _, _ = run_dump(FakeScanner(value * FLASH_SIZE))
                self.assertEqual(exit_code, flash_dump.EXIT_UNIFORM)

    def test_ignored_address_stops_at_the_check(self):
        for auto_increment in (True, False):
            with self.subTest(auto_increment=auto_increment):
                scanner = FakeScanner(patterned_flash(), address_decoder=lambda address: None,
                                      auto_increment=auto_increment)
                self.assertEqual(run_dump(scanner)[0], flash_dump.EXIT_ADDRESSING)

    def test_ignored_address_behind_a_blank_start_is_caught_by_the_descending_pass(self):
        scanner = FakeScanner(blank_start_flash(), address_decoder=lambda address: None)
        self.assertEqual(run_dump(scanner)[0], flash_dump.EXIT_PASSES_DIFFER)

    def test_dropped_address_bits_never_exit_zero(self):
        decoders = {"le16": lambda address: address & 0xFFFF,
                    "bit_12_dropped": lambda address: address & ~0x1000,
                    "be24": big_endian_24_of_first_bytes}
        for flash_name, flash in (("patterned", patterned_flash()), ("blank_start", blank_start_flash())):
            for decoder_name, decoder in decoders.items():
                with self.subTest(flash=flash_name, decoder=decoder_name):
                    exit_code = run_dump(FakeScanner(flash, address_decoder=decoder))[0]
                    self.assertIn(exit_code, (flash_dump.EXIT_ADDRESSING, flash_dump.EXIT_ALIASED))

    def test_short_data_read_is_an_error(self):
        scanner = FakeScanner(patterned_flash(), data_length=63)
        self.assertEqual(run_dump(scanner)[0], flash_dump.EXIT_USB_ERROR)

    def test_short_jedec_id_is_an_error(self):
        scanner = FakeScanner(patterned_flash(), jedec_id=b"\xc2\x20")
        self.assertEqual(run_dump(scanner)[0], flash_dump.EXIT_USB_ERROR)

    def test_short_address_write_is_an_error(self):
        scanner = FakeScanner(patterned_flash(), short_address_write=True)
        self.assertEqual(run_dump(scanner)[0], flash_dump.EXIT_USB_ERROR)

    def test_disconnect_during_a_pass_keeps_the_blocks_read(self):
        flash = patterned_flash()
        scanner = FakeScanner(flash, data_reads_before_disconnect=3 + 100)
        exit_code, images, log_text = run_dump(scanner)
        self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
        self.assertEqual(images[0], flash[:100 * 64])
        self.assertIn('"kind": "error"', log_text)

    def test_unusable_jedec_ids_stop_before_any_address_write(self):
        for jedec_id in ("ffffff", "000000", "c22014", "c2200f"):
            with self.subTest(jedec_id=jedec_id):
                scanner = FakeScanner(patterned_flash(), jedec_id=bytes.fromhex(jedec_id))
                self.assertEqual(run_dump(scanner)[0], flash_dump.EXIT_BAD_JEDEC_ID)
                self.assertNotIn(flash_dump.ADDRESS_INDEX, [index for index, _ in scanner.writes])

    def test_id_only_stops_after_the_id(self):
        exit_code, images, _ = run_dump(FakeScanner(patterned_flash()), id_only=True)
        self.assertEqual(exit_code, flash_dump.EXIT_GOOD)
        self.assertEqual(images, [None, None])


class AliasedAddressBitsTests(unittest.TestCase):
    def test_distinct_blocks_alias_nowhere(self):
        self.assertEqual(flash_dump.aliased_address_bits(patterned_flash()), [])

    def test_repeated_halves_alias_on_the_top_bit(self):
        half = patterned_flash()[:FLASH_SIZE // 2]
        self.assertEqual(flash_dump.aliased_address_bits(half + half), [18])


class CheckWriteAllowedTests(unittest.TestCase):
    def test_program_and_erase_requests_are_refused(self):
        for index in flash_dump.REFUSED_WRITE_INDICES:
            with self.subTest(index=index):
                with self.assertRaises(PermissionError):
                    flash_dump.check_write_allowed(index, bytes(4), FLASH_SIZE)

    def test_addresses_outside_the_flash_or_unaligned_are_refused(self):
        for address in (FLASH_SIZE, 0x20, FLASH_SIZE + 64):
            with self.subTest(address=address):
                with self.assertRaises(PermissionError):
                    flash_dump.check_write_allowed(flash_dump.ADDRESS_INDEX, struct.pack("<I", address), FLASH_SIZE)

    def test_spi_init_values_are_fixed(self):
        with self.assertRaises(PermissionError):
            flash_dump.check_write_allowed(flash_dump.SPI_ENABLE_INDEX, b"\x00", FLASH_SIZE)
        with self.assertRaises(PermissionError):
            flash_dump.check_write_allowed(flash_dump.SPI_SETUP_INDEX, b"\x00\x00\x00\x01", FLASH_SIZE)


class ProbeIsRunningTests(unittest.TestCase):
    def fake_proc(self, directory, command_lines):
        for pid, arguments in enumerate(command_lines, start=100):
            process = pathlib.Path(directory) / str(pid)
            process.mkdir()
            (process / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")

    def test_finds_the_watcher_started_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, [[b"sudo", b"/home/pi/plustek-preservation/venv/bin/python",
                                        b"/home/pi/plustek-preservation/probe_readonly.py", b"--watch", b"20"]])
            self.assertTrue(flash_dump.probe_is_running(pathlib.Path(directory)))

    def test_finds_the_watcher_started_keep_awake(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, [[b"sudo", b"-n", b"/home/pi/plustek-preservation/venv/bin/python",
                                        b"/home/pi/plustek-preservation/keep_awake.py",
                                        b"/home/pi/scanner-log/keep-awake-20261014T061710Z.jsonl"]])
            self.assertTrue(flash_dump.probe_is_running(pathlib.Path(directory)))

    def test_ignores_other_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, [[b"/bin/sh", b"./watch-scanner.sh"], [b"python", b"flash_dump.py", b"out"]])
            self.assertFalse(flash_dump.probe_is_running(pathlib.Path(directory)))


if __name__ == "__main__":
    unittest.main()
