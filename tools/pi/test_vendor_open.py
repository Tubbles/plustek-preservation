"""Tests for vendor_open.py against a simulated scanner and the issue #151 capture, no USB needed.

The capture tests read work/captures/151/transfers.jsonl (untracked) and
are skipped when it is missing.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import argparse
import contextlib
import dataclasses
import errno
import io
import json
import pathlib
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
import vendor_open

CAPTURE_PATH = pathlib.Path(__file__).resolve().parents[2] / "work" / "captures" / "151" / "transfers.jsonl"
CAPTURE_MISSING = f"capture not available at {CAPTURE_PATH} (work/ is untracked)"
FIRST_FRAME = 15
LAST_FRAME = 138
LINK_CHECK_TRANSFER = (0xC0, 0x0C, 0x008E, 0x0020, 1)
PAUSE_THRESHOLD_MILLISECONDS = 5.0  # longer idle gaps are pauses the tool keeps, shorter ones host overhead
PRE_OPEN_TRANSFERS = len(vendor_open.LOGGED_REGISTERS)
OPEN_TRANSFERS = sum(1 + record.link_check_after for record in vendor_open.OPEN_SEQUENCE)
POLL_TRANSFERS = 2

# 0x31 answers in turn: before the open, then frames 127 and 133 as the working unit gave them.
WORKING_UNIT_REGISTERS = {0x101: 0xDC, 0x31: [0xBC, 0xBE, 0x3E], 0x34: 0x00, 0x36: 0xFC, 0x33: 0x0E, 0x0A: 0x40,
                          0x02: 0x00, 0x06: 0x18}
# 0x101, 0x31, 0x33, 0x36 and 0x06 as the owner's unit read before the opening (doc/hardware/usb.md,
# "Read-only probe"), 0x34 as read since (doc/vendor-driver/macos.md, "Standby"). 0x0a and 0x02 are made up.
OWNER_UNIT_REGISTERS = {0x101: 0x4C, 0x31: 0xBC, 0x34: 0x00, 0x36: 0x00, 0x33: 0x1E, 0x0A: 0x40, 0x02: 0x00,
                        0x06: 0x00}


def capture_records(path: pathlib.Path) -> list:
    """Frames 15 to 138 of the device address the open is sent to."""
    records = []
    with open(path) as handle:
        for line in handle:
            record = json.loads(line)
            if record["frame"] > LAST_FRAME:
                break
            if record["frame"] >= FIRST_FRAME:
                records.append(record)
    return [record for record in records if record["device"] == records[0]["device"]]


def submits_with_answers(records: list) -> list:
    """(submit record, answer bytes, idle milliseconds since the previous completion) for every request."""
    result = []
    previous_completion = None
    for position, record in enumerate(records):
        if record["event"] == "complete":
            previous_completion = record["relative_time"]
            continue
        completion = records[position + 1]
        if completion["event"] != "complete" or completion["irp_id"] != record["irp_id"]:
            raise AssertionError(f"frame {record['frame']}: no completion right after the submit")
        idle = 0.0 if previous_completion is None else (record["relative_time"] - previous_completion) * 1000
        result.append((record, bytes.fromhex(completion["data_hex"]), idle))
    return result


def setup_of(submit: dict) -> tuple:
    setup = submit["setup"]
    return setup["bmRequestType"], setup["bRequest"], setup["wValue"], setup["wIndex"], setup["wLength"]


def kind_of(request_type: int, value: int, index: int) -> str:
    if request_type == 0x40:
        return {0x0083: "register_write", 0x0183: "register_write", 0x008C: "usb_register_write",
                0x008B: "flash_write"}[value]
    if value in (0x008E, 0x018E) and index & 0xFF == 0x22:
        return "register_read"
    if value == 0x008A and index in (0x000F, 0x0010):
        return "flash_read"
    return "vendor_read"


def request_from_capture(submit: dict, answer: bytes, idle: float) -> vendor_open.CapturedRequest:
    request_type, request, value, index, length = setup_of(submit)
    sent = bytes.fromhex(submit["data_hex"])
    answer = answer if request_type == 0xC0 else b""
    if length != len(sent) + len(answer):
        raise AssertionError(f"frame {submit['frame']}: wLength {length}, {len(sent) + len(answer)} bytes")
    pause = round(idle, 1) if idle > PAUSE_THRESHOLD_MILLISECONDS else 0.0
    return vendor_open.CapturedRequest(submit["frame"], kind_of(request_type, value, index), request_type, request,
                                       value, index, sent, answer, False, pause)


def requests_from_capture(path: pathlib.Path) -> list:
    """The capture's open as CapturedRequest records: link checks folded into the request before them."""
    requests = []
    for submit, answer, idle in submits_with_answers(capture_records(path)):
        if setup_of(submit) != LINK_CHECK_TRANSFER:
            requests.append(request_from_capture(submit, answer, idle))
            continue
        if answer != b"\x55" or idle > PAUSE_THRESHOLD_MILLISECONDS or requests[-1].request_type != 0x40:
            raise AssertionError(f"frame {submit['frame']}: link check the table cannot express")
        requests[-1] = dataclasses.replace(requests[-1], link_check_after=True)
    return requests


def transfers_from_capture(path: pathlib.Path) -> list:
    """Every request of the capture's open, link checks included, as the fake records transfers."""
    transfers = []
    for submit, _, _ in submits_with_answers(capture_records(path)):
        request_type, request, value, index, length = setup_of(submit)
        payload = bytes.fromhex(submit["data_hex"]) if request_type == 0x40 else length
        transfers.append((request_type, request, value, index, payload))
    return transfers


def table_record(frame: int) -> vendor_open.CapturedRequest:
    return next(record for record in vendor_open.OPEN_SEQUENCE if record.frame == frame)


def transfers_before(frame: int) -> int:
    """How many transfers a run sends before the one of the given capture frame."""
    earlier = [record for record in vendor_open.OPEN_SEQUENCE if record.frame < frame]
    return PRE_OPEN_TRANSFERS + sum(1 + record.link_check_after for record in earlier)


class FakeScanner:
    """Answers the requests vendor_open may send, with the Windows framing. Anything else fails the test.

    register_values maps a register to a value or to a list of values
    returned in turn (the last one repeats). fail_on is a predicate on the
    transfer tuple that makes that transfer raise "Pipe error";
    disconnect_after makes every later transfer raise disconnect_error.
    """

    def __init__(self, register_values=None, flash_block=None, bcd_device=0x0702, bad_link_check_number=None,
                 bad_register_read_number=None, short_write_data=None, fail_on=None, disconnect_after=None,
                 disconnect_error=None):
        values = register_values if register_values is not None else WORKING_UNIT_REGISTERS
        self.register_values = {register: list(value) if isinstance(value, list) else value
                                for register, value in values.items()}
        self.flash_block = flash_block if flash_block is not None else table_record(71).answer
        self.bcdDevice = bcd_device
        self.idVendor, self.idProduct, self.bus, self.address = 0x07B3, 0x1406, 1, 5
        self.bad_link_check_number = bad_link_check_number
        self.bad_register_read_number = bad_register_read_number
        self.short_write_data = short_write_data
        self.fail_on = fail_on
        self.disconnect_after = disconnect_after
        self.disconnect_error = disconnect_error or usb.core.USBError("No such device (it may have been disconnected)")
        self.transfers = []
        self.link_checks = 0
        self.register_reads = 0

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        payload = bytes(data_or_length) if request_type == 0x40 else data_or_length
        self.transfers.append((request_type, request, value, index, payload))
        if self.disconnect_after is not None and len(self.transfers) > self.disconnect_after:
            raise self.disconnect_error
        if self.fail_on is not None and self.fail_on(self.transfers[-1]):
            raise usb.core.USBError("Pipe error")
        length = len(payload) if request_type == 0x40 else payload
        if request != flash_dump.request_code_for(length):
            raise AssertionError(f"bRequest 0x{request:02x} for {length} bytes")
        if request_type == 0x40:
            return self.handle_write(value, index, payload)
        if request_type == 0xC0:
            return self.handle_read(value, index, length)
        raise AssertionError(f"bmRequestType 0x{request_type:02x}")

    def handle_write(self, value, index, data):
        if value not in (0x0083, 0x0183, 0x008C, 0x008B):
            raise AssertionError(f"OUT wValue 0x{value:04x}")
        if value == 0x0083 and 0x0F in data[0::2]:
            raise AssertionError("motor start")
        if value == 0x008B and index not in (0x07, 0x09, 0x0B):
            raise AssertionError(f"flash request wIndex 0x{index:02x}")
        return len(data) - 1 if data == self.short_write_data else len(data)

    def handle_read(self, value, index, length):
        if (value, index, length) == (0x008E, 0x0020, 1):
            self.link_checks += 1
            return b"\xaa" if self.link_checks == self.bad_link_check_number else b"\x55"
        if value in (0x008E, 0x018E) and index & 0xFF == 0x22 and length == 2:
            self.register_reads += 1
            link = 0x00 if self.register_reads == self.bad_register_read_number else 0x55
            return bytes([self.next_register_value((index >> 8) | (value & 0x100)), link])
        other_reads = {(0x008A, 0x26FE, 1): b"\x00", (0x008E, 0x0000, 1): b"\x00",
                       (0x008A, 0x0010, 3): bytes.fromhex("c22013"), (0x008A, 0x000F, 64): self.flash_block}
        if (value, index, length) not in other_reads:
            raise AssertionError(f"IN wValue 0x{value:04x} wIndex 0x{index:04x}")
        return other_reads[(value, index, length)]

    def next_register_value(self, register):
        if register not in self.register_values:
            raise AssertionError(f"read of register 0x{register:02x}")
        value = self.register_values[register]
        if not isinstance(value, list):
            return value
        return value.pop(0) if len(value) > 1 else value[0]


class FakeClock:
    """Monotonic time that only sleeps advance. find_device gives the scanner until gone_at_seconds."""

    def __init__(self, scanner, gone_at_seconds=None, found_instead=None):
        self.scanner = scanner
        self.now = 0.0
        self.sleeps = []
        self.gone_at_seconds = gone_at_seconds
        self.found_instead = found_instead

    def sleep(self, seconds):
        self.sleeps.append((len(self.scanner.transfers), seconds))
        self.now += seconds

    def monotonic(self):
        return self.now

    def find_device(self):
        if self.gone_at_seconds is not None and self.now >= self.gone_at_seconds:
            return self.found_instead
        return self.scanner

    def environment(self):
        return vendor_open.Environment(sleep=self.sleep, monotonic=self.monotonic, find_device=self.find_device)


def run_open(scanner, clock=None, watch_seconds=vendor_open.DEFAULT_WATCH_SECONDS, carrier_off_home_ok=False):
    """Run run(); return the exit code and the log records."""
    clock = clock or FakeClock(scanner)
    log_file = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()):
        exit_code = vendor_open.run(flash_dump.Session(scanner, log_file), clock.environment(), watch_seconds,
                                    carrier_off_home_ok)
    return exit_code, [json.loads(line) for line in log_file.getvalue().splitlines()]


def records_of_kind(records, kind):
    return [record for record in records if record["kind"] == kind]


def read_records(records):
    return {record["frame"]: record for record in records if "differs" in record}


@unittest.skipUnless(CAPTURE_PATH.exists(), CAPTURE_MISSING)
class CaptureTests(unittest.TestCase):
    def test_table_equals_the_capture(self):
        from_capture = requests_from_capture(CAPTURE_PATH)
        self.assertEqual(len(from_capture), len(vendor_open.OPEN_SEQUENCE))
        for expected, actual in zip(from_capture, vendor_open.OPEN_SEQUENCE):
            with self.subTest(frame=expected.frame):
                self.assertEqual(actual, expected)

    def test_a_run_sends_the_capture_byte_for_byte(self):
        scanner = FakeScanner()
        self.assertEqual(run_open(scanner, watch_seconds=0)[0], vendor_open.EXIT_GOOD)
        sent = scanner.transfers[PRE_OPEN_TRANSFERS:PRE_OPEN_TRANSFERS + OPEN_TRANSFERS]
        self.assertEqual(sent, transfers_from_capture(CAPTURE_PATH))


class TableTests(unittest.TestCase):
    def test_shape(self):
        frames = [record.frame for record in vendor_open.OPEN_SEQUENCE]
        self.assertEqual(len(frames), 36)
        self.assertEqual(frames, sorted(set(frames)))
        self.assertTrue(FIRST_FRAME == frames[0] and frames[-1] <= LAST_FRAME)
        self.assertEqual([len(table_record(frame).sent) // 2 for frame in (17, 21, 25, 29)], [32, 32, 32, 20])
        for record in vendor_open.OPEN_SEQUENCE:
            self.assertEqual(record.link_check_after, record.request_type == 0x40)

    def test_every_record_passes_the_checks_and_none_starts_the_motor(self):
        for record in vendor_open.OPEN_SEQUENCE:
            with self.subTest(frame=record.frame):
                vendor_open.check_allowed(record)
                self.assertNotIn(0x0F, vendor_open.written_registers(record))


class OpenTests(unittest.TestCase):
    def test_working_unit_answers_give_no_difference_and_exit_zero(self):
        exit_code, records = run_open(FakeScanner())
        self.assertEqual(exit_code, vendor_open.EXIT_GOOD)
        reads = read_records(records)
        self.assertEqual(sorted(reads), [15, 65, 71, 73, 75, 113, 119, 125, 127, 133])
        self.assertFalse(any(record["differs"] for record in reads.values()))
        self.assertEqual(len(records_of_kind(records, "link_check")), 26)

    def test_differences_are_logged_and_do_not_stop_the_run(self):
        scanner = FakeScanner(OWNER_UNIT_REGISTERS, flash_block=b"\xff" * 64)
        exit_code, records = run_open(scanner)
        self.assertEqual(exit_code, vendor_open.EXIT_GOOD)
        reads = read_records(records)
        self.assertEqual(sorted(frame for frame, record in reads.items() if record["differs"]),
                         [71, 73, 75, 113, 119, 127, 133])
        self.assertEqual((reads[113]["received"], reads[113]["captured"]), ("00 55", "fc 55"))
        self.assertEqual(len(scanner.transfers), PRE_OPEN_TRANSFERS + OPEN_TRANSFERS + 22 * POLL_TRANSFERS)

    def test_registers_are_read_and_logged_before_the_open(self):
        scanner = FakeScanner(OWNER_UNIT_REGISTERS)
        _, records = run_open(scanner, watch_seconds=0)
        expected = [(0xC0, 0x04, 0x018E if register > 0xFF else 0x008E, 0x22 + ((register & 0xFF) << 8), 2)
                    for register in vendor_open.LOGGED_REGISTERS]
        self.assertEqual(scanner.transfers[:PRE_OPEN_TRANSFERS], expected)
        before = records_of_kind(records, "registers_before_open")[0]
        self.assertEqual((before["0x101"], before["0x31"], before["0x36"]), ("4c", "bc", "00"))

    def test_capture_pauses_are_kept_where_the_capture_has_them(self):
        scanner = FakeScanner()
        clock = FakeClock(scanner)
        run_open(scanner, clock, watch_seconds=0)
        self.assertEqual([count for count, _ in clock.sleeps], [transfers_before(frame) for frame in (17, 57, 73, 133)])
        for (_, seconds), expected in zip(clock.sleeps, (0.0266, 0.0124, 0.0683, 0.0123)):
            self.assertAlmostEqual(seconds, expected)

    def test_standby_pulse_is_write_link_check_pause_read_write(self):
        scanner = FakeScanner()
        clock = FakeClock(scanner)
        run_open(scanner, clock, watch_seconds=0)
        pause_at = clock.sleeps[3][0]
        self.assertEqual(scanner.transfers[pause_at - 2:pause_at + 2],
                         [(0x40, 0x04, 0x0083, 0, b"\x31\x3e"), LINK_CHECK_TRANSFER,
                          (0xC0, 0x04, 0x008E, 0x3122, 2), (0x40, 0x04, 0x0083, 0, b"\x31\xbe")])


class HomeGateTests(unittest.TestCase):
    def test_carrier_off_home_or_motor_enabled_sends_no_write_and_exits_21(self):
        for status in (0x44, 0xDD):
            with self.subTest(status=f"{status:02x}"):
                scanner = FakeScanner({**OWNER_UNIT_REGISTERS, 0x101: status})
                exit_code, records = run_open(scanner)
                self.assertEqual(exit_code, vendor_open.EXIT_CARRIER_NOT_HOME)
                self.assertEqual(exit_code, 21)
                self.assertFalse(any(transfer[0] == 0x40 for transfer in scanner.transfers))
                self.assertEqual(len(scanner.transfers), PRE_OPEN_TRANSFERS)
                self.assertEqual(records_of_kind(records, "refused")[0]["0x101"], f"{status:02x}")

    def test_flag_lets_the_run_proceed(self):
        scanner = FakeScanner({**OWNER_UNIT_REGISTERS, 0x101: 0x44})
        exit_code, records = run_open(scanner, carrier_off_home_ok=True)
        self.assertEqual(exit_code, vendor_open.EXIT_GOOD)
        self.assertEqual(records_of_kind(records, "home_gate_skipped")[0]["0x101"], "44")
        self.assertEqual(len(scanner.transfers), PRE_OPEN_TRANSFERS + OPEN_TRANSFERS + 22 * POLL_TRANSFERS)

    def test_gate_passes_the_values_both_units_read_at_rest(self):
        self.assertTrue(vendor_open.carrier_at_rest_at_home(0xDC))  # working unit, capture frames 73 and 75
        self.assertTrue(vendor_open.carrier_at_rest_at_home(0x4C))  # owner's unit before the opening
        for status in (0x44, 0xDD, 0x4D, 0x00):
            self.assertFalse(vendor_open.carrier_at_rest_at_home(status))

    def test_command_line_flag(self):
        parser = vendor_open.argument_parser()
        self.assertFalse(parser.parse_args(["logs"]).carrier_off_home_ok)
        self.assertTrue(parser.parse_args(["logs", "--carrier-off-home-ok"]).carrier_off_home_ok)


class ErrorTests(unittest.TestCase):
    def assert_stopped_at(self, scanner, frame, last_transfer):
        exit_code, records = run_open(scanner)
        self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
        self.assertEqual(records_of_kind(records, "error")[0]["frame"], frame)
        self.assertEqual(scanner.transfers[-1], last_transfer)
        self.assertEqual(records_of_kind(records, "watch"), [])

    def test_usb_error_stops_at_its_frame(self):
        scanner = FakeScanner(fail_on=lambda transfer: transfer[4] == table_record(29).sent)
        self.assert_stopped_at(scanner, 29, (0x40, 0x04, 0x0083, 0, table_record(29).sent))

    def test_short_write_stops_at_its_frame(self):
        scanner = FakeScanner(short_write_data=b"\x0b\x64")
        self.assert_stopped_at(scanner, 45, (0x40, 0x04, 0x0083, 0, b"\x0b\x64"))

    def test_short_read_stops_at_its_frame(self):
        scanner = FakeScanner(flash_block=b"\xff" * 63)
        self.assert_stopped_at(scanner, 71, (0xC0, 0x04, 0x008A, 0x000F, 64))

    def test_bad_link_check_stops_at_the_write_before_it(self):
        scanner = FakeScanner(bad_link_check_number=3)
        self.assert_stopped_at(scanner, 25, LINK_CHECK_TRANSFER)

    def test_register_read_without_0x55_stops_at_its_frame(self):
        scanner = FakeScanner(bad_register_read_number=PRE_OPEN_TRANSFERS + 1)
        self.assert_stopped_at(scanner, 73, (0xC0, 0x04, 0x018E, 0x0122, 2))

    def test_error_before_the_open_sends_no_write(self):
        for scanner in (FakeScanner(bad_register_read_number=2), FakeScanner(disconnect_after=3)):
            with self.subTest(scanner=scanner):
                exit_code, records = run_open(scanner)
                self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
                self.assertNotIn("frame", records_of_kind(records, "error")[0])
                self.assertFalse(any(transfer[0] == 0x40 for transfer in scanner.transfers))

    def test_disconnect_during_the_open_is_a_usb_error(self):
        scanner = FakeScanner(disconnect_after=transfers_before(113))
        self.assert_stopped_at(scanner, 113, (0xC0, 0x04, 0x008E, 0x3622, 2))


class WatchTests(unittest.TestCase):
    def test_watch_polls_every_20_seconds_and_exits_zero(self):
        scanner = FakeScanner()
        exit_code, records = run_open(scanner)
        self.assertEqual(exit_code, vendor_open.EXIT_GOOD)
        polls = records_of_kind(records, "watch")
        self.assertEqual([poll["seconds_since_open"] for poll in polls], [20.0 * number for number in range(22)])
        self.assertEqual({(poll["link_check"], poll["0x101"]) for poll in polls}, {("55", "dc")})
        self.assertEqual(scanner.transfers[-2:], [LINK_CHECK_TRANSFER, (0xC0, 0x04, 0x018E, 0x0122, 2)])

    def test_zero_watch_seconds_polls_once(self):
        _, records = run_open(FakeScanner(), watch_seconds=0)
        self.assertEqual(len(records_of_kind(records, "watch")), 1)

    def test_no_such_device_ends_the_watch_with_the_elapsed_time(self):
        disconnect_errors = {"message": usb.core.USBError("No such device (it may have been disconnected)"),
                             "errno": usb.core.USBError("Input/Output Error")}
        disconnect_errors["errno"].errno = errno.ENODEV
        for name, error in disconnect_errors.items():
            with self.subTest(error=name):
                scanner = FakeScanner(disconnect_after=PRE_OPEN_TRANSFERS + OPEN_TRANSFERS + 16 * POLL_TRANSFERS,
                                      disconnect_error=error)
                exit_code, records = run_open(scanner)
                self.assertEqual(exit_code, vendor_open.EXIT_DROPPED)
                self.assertEqual(records_of_kind(records, "dropped")[0]["seconds_since_open"], 320.0)
                self.assertEqual(len(records_of_kind(records, "watch")), 16)

    def test_failed_refind_ends_the_watch(self):
        for found_instead in (None, types.SimpleNamespace(bus=1, address=6)):
            with self.subTest(found_instead=found_instead):
                scanner = FakeScanner()
                exit_code, records = run_open(scanner, FakeClock(scanner, 300, found_instead))
                self.assertEqual(exit_code, vendor_open.EXIT_DROPPED)
                self.assertEqual(records_of_kind(records, "dropped")[0]["seconds_since_open"], 300.0)
                self.assertEqual(len(scanner.transfers), PRE_OPEN_TRANSFERS + OPEN_TRANSFERS + 15 * POLL_TRANSFERS)

    def test_other_usb_error_with_the_scanner_present_is_exit_13_without_a_retry(self):
        first_watch_transfer = PRE_OPEN_TRANSFERS + OPEN_TRANSFERS + 1
        scanner = FakeScanner()
        scanner.fail_on = lambda transfer: len(scanner.transfers) == first_watch_transfer
        clock = FakeClock(scanner)
        self.assertEqual(run_open(scanner, clock)[0], flash_dump.EXIT_USB_ERROR)
        self.assertEqual(clock.sleeps[-1], (first_watch_transfer, vendor_open.REFIND_DELAY_SECONDS))
        self.assertEqual(len(scanner.transfers), first_watch_transfer)

    def test_other_usb_error_then_no_scanner_after_the_delay_is_the_drop(self):
        failing_transfer = PRE_OPEN_TRANSFERS + OPEN_TRANSFERS + 5 * POLL_TRANSFERS + 1
        scanner = FakeScanner()
        scanner.fail_on = lambda transfer: len(scanner.transfers) == failing_transfer
        exit_code, records = run_open(scanner, FakeClock(scanner, gone_at_seconds=101))
        self.assertEqual(exit_code, vendor_open.EXIT_DROPPED)
        dropped = records_of_kind(records, "dropped")[0]
        self.assertEqual(dropped["seconds_since_open"], 102.0)
        self.assertIn("Pipe error", dropped["reason"])
        self.assertEqual(len(scanner.transfers), failing_transfer)

    def test_link_byte_in_the_watch_is_only_logged(self):
        scanner = FakeScanner(bad_link_check_number=26 + 3)
        exit_code, records = run_open(scanner)
        self.assertEqual(exit_code, vendor_open.EXIT_GOOD)
        self.assertEqual([poll["link_check"] for poll in records_of_kind(records, "watch")][:4],
                         ["55", "55", "aa", "55"])

    def test_0x101_read_without_0x55_in_the_watch_is_exit_13(self):
        open_register_reads = sum(record.kind == "register_read" for record in vendor_open.OPEN_SEQUENCE)
        scanner = FakeScanner(bad_register_read_number=PRE_OPEN_TRANSFERS + open_register_reads + 3)
        exit_code, records = run_open(scanner)
        self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
        self.assertEqual(len(records_of_kind(records, "watch")), 2)


class SafetyTests(unittest.TestCase):
    def refused(self, record):
        scanner = FakeScanner()
        with self.assertRaises(PermissionError):
            vendor_open.transfer(flash_dump.Session(scanner, io.StringIO()), record)
        self.assertEqual(scanner.transfers, [])

    def test_records_not_in_the_table_never_reach_the_device(self):
        blast = table_record(17)
        for changed in ({"sent": blast.sent[:-1] + b"\x01"}, {"frame": 139}, {"index": 1}, {"request": 0x0C},
                        {"link_check_after": False}, {"pause_before_milliseconds": 0.0}):
            with self.subTest(changed=changed):
                self.refused(dataclasses.replace(blast, **changed))
        self.refused(dataclasses.replace(table_record(73), answer=b"\xdc"))

    def test_motor_start_is_refused(self):
        for sent in (b"\x0f\x01", table_record(29).sent[:-2] + b"\x0f\x01"):
            with self.subTest(sent=sent):
                record = dataclasses.replace(table_record(45), sent=sent)
                with self.assertRaisesRegex(PermissionError, "0x0f"):
                    vendor_open.check_allowed(record)

    def test_flash_program_and_erase_are_refused(self):
        for index in flash_dump.REFUSED_WRITE_INDICES:
            with self.subTest(index=index):
                record = dataclasses.replace(table_record(67), index=index)
                with self.assertRaisesRegex(PermissionError, "refusing write"):
                    vendor_open.check_allowed(record)

    def test_flash_address_beyond_the_first_block_is_refused(self):
        record = dataclasses.replace(table_record(67), sent=bytes.fromhex("40000000"))
        with self.assertRaisesRegex(PermissionError, "outside the flash"):
            vendor_open.check_allowed(record)

    def test_reads_outside_the_list_are_refused(self):
        scanner = FakeScanner()
        for register in (0x0F, 0x100, 0x8B, 0x37):
            with self.subTest(register=register):
                with self.assertRaises(PermissionError):
                    vendor_open.read_register(flash_dump.Session(scanner, io.StringIO()), register)
        self.assertEqual(scanner.transfers, [])


class RefusalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = pathlib.Path(directory.name)
        self.probe_disabled = self.directory / "probe-disabled"
        self.probe_disabled.touch()
        self.proc_root = self.directory / "proc"
        self.proc_root.mkdir()

    def add_process(self, pid, arguments):
        (self.proc_root / str(pid)).mkdir()
        (self.proc_root / str(pid) / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")

    def refusal(self, device):
        return vendor_open.refusal_exit_code(self.probe_disabled, self.proc_root, device)

    def test_good_start(self):
        self.add_process(100, [b"/bin/sh", b"./watch-scanner.sh"])
        self.assertIsNone(self.refusal(FakeScanner()))

    def test_missing_probe_disabled_is_exit_16(self):
        self.probe_disabled.unlink()
        self.assertEqual(self.refusal(FakeScanner()), flash_dump.EXIT_PROBE_ACTIVE)

    def test_running_probe_or_keep_awake_is_exit_16(self):
        for script in (b"probe_readonly.py", b"keep_awake.py"):
            with self.subTest(script=script):
                self.proc_root = self.directory / script.decode()
                self.proc_root.mkdir()
                self.add_process(100, [b"sudo", b"/home/pi/plustek-preservation/venv/bin/python",
                                       b"/home/pi/plustek-preservation/" + script])
                self.assertEqual(self.refusal(FakeScanner()), flash_dump.EXIT_PROBE_ACTIVE)

    def test_no_scanner_is_exit_10(self):
        self.assertEqual(self.refusal(None), flash_dump.EXIT_NOT_FOUND)

    def test_other_bcd_device_is_exit_19(self):
        self.assertEqual(self.refusal(FakeScanner(bcd_device=0x0701)), vendor_open.EXIT_WRONG_CHIP)


class ArgumentTests(unittest.TestCase):
    def test_watch_seconds(self):
        self.assertEqual(vendor_open.watch_seconds_argument("420"), 420)
        self.assertEqual(vendor_open.watch_seconds_argument("0"), 0)
        with self.assertRaises(argparse.ArgumentTypeError):
            vendor_open.watch_seconds_argument("-1")
        with self.assertRaises(ValueError):
            vendor_open.watch_seconds_argument("seven")

    def test_exit_codes(self):
        self.assertEqual((vendor_open.EXIT_GOOD, flash_dump.EXIT_NOT_FOUND, vendor_open.EXIT_USB_ERROR,
                          vendor_open.EXIT_PROBE_ACTIVE, vendor_open.EXIT_WRONG_CHIP, vendor_open.EXIT_DROPPED,
                          vendor_open.EXIT_CARRIER_NOT_HOME),
                         (0, 10, 13, 16, 19, 20, 21))


if __name__ == "__main__":
    unittest.main()
