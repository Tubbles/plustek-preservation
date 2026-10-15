"""Tests for move_carrier.py against a simulated scanner and the issue #151 capture, no USB needed.

The capture tests read work/captures/151/transfers.jsonl (untracked) and
are skipped when it is missing.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import argparse
import contextlib
import dataclasses
import hashlib
import io
import json
import pathlib
import re
import sys
import tempfile
import types
import unittest
import unittest.mock

if "usb.core" not in sys.modules:
    usb_stub = types.ModuleType("usb")
    usb_core_stub = types.ModuleType("usb.core")
    setattr(usb_core_stub, "USBError", type("USBError", (Exception,), {}))
    setattr(usb_stub, "core", usb_core_stub)
    sys.modules["usb"] = usb_stub
    sys.modules["usb.core"] = usb_core_stub

import usb.core

import flash_dump
import move_carrier
import vendor_open

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
CAPTURE_PATH = REPOSITORY / "work" / "captures" / "151" / "transfers.jsonl"
CAPTURE_MISSING = f"capture not available at {CAPTURE_PATH} (work/ is untracked)"
TABLES_DIRECTORY = REPOSITORY / "doc" / "protocol" / "tables"
FIRST_FRAME = 15
START_FRAME = 6483
MOVE_FIRST_FRAME = 6445
MOVE_LAST_FRAME = 6644
TABLE_SHA256 = hashlib.sha256(move_carrier.SLOPE_TABLE).hexdigest()

LINK_CHECK_TRANSFER = (0xC0, 0x0C, 0x008E, 0x0020, 1)
UPLOAD_STATUS_TRANSFER = (0xC0, 0x0C, 0x008E, 0x0018, 1)
TABLE_TRANSFER = ("bulk", 0x02, TABLE_SHA256)
# Not in the register state (move_carrier docstring, step 3): the lamp, commands, and what the move sequence
# writes itself, including the 19 registers of the block at frame 6463.
EXCLUDED_REGISTERS = {0x03, 0x0D, 0x0F, 0x02, 0x0A, 0x09, 0x33}
FEED_BLOCK_REGISTERS = {0x1C, 0x3D, 0x3E, 0x3F, 0x7D, 0x7E, 0x7F, 0x8A, 0x8B, 0x8C, 0x8D, 0x8E, 0x8F, 0x90, 0x91,
                        0x92, 0x02, 0xAE, 0xAF}
AFE_REGISTERS = {0x51, 0x5D, 0x5E}
FEED_BLOCK_97 = "1c00 3d00 3e00 3f61 7d00 7e99 7f99 8a00 8b55 8c00 8d00 8e55 8f00 9001 9154 9200 0218 ae00 afff"
# 0x101 as the working unit answered the polls of move 3, frames 6487 to 6628 (doc/protocol/of120-moves.md).
MOVE_3_POLLS = [0xD5] * 38 + [0xF5] * 32 + [0xF4]
# Gate read 0xf4 (frame 6433), the polls, then 0xf4 at frame 6643. 0x33 answers in turn: before the move (frame
# 6435), frame 6449, frame 6629, after the move. 0x31 as read at frames 6005 and 7315, 0x36 as at 7293.
WORKING_UNIT_REGISTERS = {0x101: [0xF4] + MOVE_3_POLLS + [0xF4], 0x31: 0xBB, 0x33: [0x3C, 0x1C, 0x3C, 0x1C],
                          0x36: 0xFE, 0x02: [0x58, 0x08]}
# The owner's unit after vendor_open.py (doc/hardware/probes/20261015T061444Z-vendor-open.jsonl): 0x101 0xdc,
# 0x33 0x0e (frame 119, then written 0x0e at 121), 0x36 0xfe as written at frame 115. The answers after the
# move's own writes, the polls, 0x31 and 0x02 are made up.
OWNER_UNIT_REGISTERS = {0x101: [0xDC, 0xDD, 0xD5, 0xD5, 0xF5, 0xF4], 0x31: 0xBC, 0x33: [0x0E, 0x1C, 0x3C, 0x1C],
                        0x36: 0xFE, 0x02: [0x78, 0x08]}

# --as-move-1
MOVE_1_START_FRAME = 6279
MOVE_1_TABLE_SHA256 = hashlib.sha256(move_carrier.SLOPE_TABLE_MOVE_1).hexdigest()
MOVE_1_TABLE_TRANSFER = ("bulk", 0x02, MOVE_1_TABLE_SHA256)
# Not in the move 1 register state: commands, the fixed 0x33 write, and the 27 registers of the block at 6259.
MOVE_1_EXCLUDED_REGISTERS = {0x0D, 0x0F, 0x33}
MOVE_1_BLOCK_REGISTERS = {0x03, 0x7D, 0x7E, 0x7F, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x2C, 0x2D, 0x04,
                          0x1D, 0x1C, 0xA4, 0xA5, 0xAA, 0xAB, 0x02, 0xAE, 0xAF, 0x3D, 0x3E, 0x3F}
MOVE_1_BLOCK_10158 = ("0330 7d00 7e99 7f99 8000 8111 8200 8302 8444 8500 8617 87ac 2c01 2de0 0442 1d20 1c00 a400 a526"
                      " aa00 ab26 0218 ae00 af7f 3d00 3e27 3fae")
# 0x101 before move 1 as read at frames 6075 and 6089, then 0xdd as at frame 6283, right after the start. The
# later polls are made up (the vendor's move 1 was cut by an interrupt). 0x33 as written at frame 6085.
WORKING_UNIT_MOVE_1_REGISTERS = {0x101: [0xDC, 0xDD, 0xD5, 0xF5, 0xF4], 0x31: 0xBB, 0x33: 0x1C, 0x36: 0xFE,
                                 0x02: [0x78, 0x08]}


def read_transfer(register):
    return (0xC0, 0x04, 0x018E if register > 0xFF else 0x008E, 0x22 + ((register & 0xFF) << 8), 2)


def write_transfer(pairs_hex, value=0x0083):
    return (0x40, 0x04, value, 0x0000, bytes.fromhex(pairs_hex))


def buffer_header_transfer(header_hex):
    return (0x40, 0x04, 0x0082, 0x0001, bytes.fromhex(header_hex))


LOGGED_READ_TRANSFERS = [read_transfer(register) for register in (0x101, 0x31, 0x33, 0x36, 0x02)]


def pairs_hex(pairs):
    return bytes(byte for pair in pairs for byte in pair).hex()


def register_state_transfers():
    """The three REGISTER_STATE transfers, then the AFE write of frame 6175, each with its link check."""
    state = move_carrier.REGISTER_STATE
    payloads = [pairs_hex(state[0:32]), pairs_hex(state[32:64]), pairs_hex(state[64:]), "51045d005e2a"]
    return [transfer for payload in payloads for transfer in (write_transfer(payload), LINK_CHECK_TRANSFER)]


def move_transfers(feedl_hex="000061", register_33_before=0x1C, register_33_after=0x3C, polls=71, backscan=False,
                   polls_after_cut=None):
    """The requests from 0x33 = 0x1c at frame 6445 to 0x02 = 0x08, as the work item and the review list them."""
    block = FEED_BLOCK_97.replace("3d00 3e00 3f61", f"3d{feedl_hex[0:2]} 3e{feedl_hex[2:4]} 3f{feedl_hex[4:6]}")
    sequence = [write_transfer("331c"), LINK_CHECK_TRANSFER, read_transfer(0x33), write_transfer("0258"),
                LINK_CHECK_TRANSFER, write_transfer("0a48"), LINK_CHECK_TRANSFER,
                write_transfer(f"33{register_33_before | 0x20:02x}"), LINK_CHECK_TRANSFER]
    if backscan:
        sequence += [write_transfer("0908"), LINK_CHECK_TRANSFER]
    sequence += [write_transfer(block), LINK_CHECK_TRANSFER,
                 buffer_header_transfer("00c0001000020000"), LINK_CHECK_TRANSFER, TABLE_TRANSFER,
                 UPLOAD_STATUS_TRANSFER,
                 buffer_header_transfer("0000011000020000"), LINK_CHECK_TRANSFER, TABLE_TRANSFER,
                 UPLOAD_STATUS_TRANSFER,
                 write_transfer("0f01"), LINK_CHECK_TRANSFER]
    sequence += [read_transfer(0x101)] * polls
    if polls_after_cut is not None:
        sequence += [write_transfer("0208"), LINK_CHECK_TRANSFER, write_transfer("3d003e003f01"),
                     LINK_CHECK_TRANSFER]
        sequence += [read_transfer(0x101)] * polls_after_cut
    if backscan:
        sequence += [write_transfer("0900"), LINK_CHECK_TRANSFER]
    return sequence + [read_transfer(0x33), write_transfer("0258"), LINK_CHECK_TRANSFER, write_transfer("0a48"),
                       LINK_CHECK_TRANSFER, write_transfer(f"33{register_33_after & 0xDF:02x}"), LINK_CHECK_TRANSFER,
                       read_transfer(0x101), write_transfer("0208"), LINK_CHECK_TRANSFER]


def run_transfers(**move_arguments):
    return (LOGGED_READ_TRANSFERS + register_state_transfers() + move_transfers(**move_arguments)
            + LOGGED_READ_TRANSFERS)


MOVE_START = len(LOGGED_READ_TRANSFERS) + len(register_state_transfers())


def move_1_state_transfers():
    """The three REGISTER_STATE_MOVE_1 transfers, then the AFE write of frame 6175, each with its link check."""
    state = move_carrier.REGISTER_STATE_MOVE_1
    payloads = [pairs_hex(state[0:32]), pairs_hex(state[32:64]), pairs_hex(state[64:]), "51045d005e2a"]
    return [transfer for payload in payloads for transfer in (write_transfer(payload), LINK_CHECK_TRANSFER)]


def move_1_transfers(feedl_hex="000061", polls=4, polls_after_cut=None):
    """From 0x33 = 0x1c (frame 6085) to the read of 0x101 after the move, as the work item lists them."""
    block = MOVE_1_BLOCK_10158.replace("3d00 3e27 3fae", f"3d{feedl_hex[0:2]} 3e{feedl_hex[2:4]} 3f{feedl_hex[4:6]}")
    sequence = [write_transfer("331c"), LINK_CHECK_TRANSFER, write_transfer(block), LINK_CHECK_TRANSFER,
                buffer_header_transfer("00c0001000020000"), LINK_CHECK_TRANSFER, MOVE_1_TABLE_TRANSFER,
                UPLOAD_STATUS_TRANSFER,
                buffer_header_transfer("0000011000020000"), LINK_CHECK_TRANSFER, MOVE_1_TABLE_TRANSFER,
                UPLOAD_STATUS_TRANSFER,
                write_transfer("0f01"), LINK_CHECK_TRANSFER]
    sequence += [read_transfer(0x101)] * polls
    if polls_after_cut is not None:
        sequence += [write_transfer("0208"), LINK_CHECK_TRANSFER, write_transfer("3d003e003f01"),
                     LINK_CHECK_TRANSFER]
        sequence += [read_transfer(0x101)] * polls_after_cut
    return sequence + [write_transfer("0208"), LINK_CHECK_TRANSFER, write_transfer("0300"), LINK_CHECK_TRANSFER,
                       read_transfer(0x101)]


def run_move_1_transfers(**move_arguments):
    return (LOGGED_READ_TRANSFERS + move_1_state_transfers() + move_1_transfers(**move_arguments)
            + LOGGED_READ_TRANSFERS)


MOVE_1_START = len(LOGGED_READ_TRANSFERS) + len(move_1_state_transfers())


def capture_records(path, first, last):
    """Records of the device the open is sent to, from frame first to frame last."""
    records = []
    with open(path) as handle:
        for line in handle:
            record = json.loads(line)
            if record["frame"] > last:
                break
            if record["frame"] >= first:
                records.append(record)
    return [record for record in records if record["device"] == records[0]["device"]]


def replay_register_writes(shadow, transfers):
    """Apply every register write (40 04 0083 and 0183) among transfers in FakeScanner form to shadow."""
    for transfer in transfers:
        if transfer[0] != 0x40 or transfer[2] not in (0x0083, 0x0183):
            continue
        page = 0x100 if transfer[2] == 0x0183 else 0
        for position in range(0, len(transfer[4]), 2):
            shadow[page | transfer[4][position]] = transfer[4][position + 1]
    return shadow


def shadow_of_capture(path, first, last):
    """Every register write from frame first to frame last, replayed in submit order."""
    submits = [record for record in capture_records(path, first, last)
               if record["event"] == "submit" and record["transfer_type"] == "control"]
    return replay_register_writes({}, [transfer_of(submit) for submit in submits])


def shadow_of_open():
    """The register writes of vendor_open.OPEN_SEQUENCE (frames 17 to 135), replayed."""
    return replay_register_writes({}, [(record.request_type, record.request, record.value, record.index, record.sent)
                                       for record in vendor_open.OPEN_SEQUENCE])


def submits_with_answers(records):
    result = []
    for position, record in enumerate(records):
        if record["event"] == "complete":
            continue
        completion = records[position + 1]
        if completion["event"] != "complete" or completion["irp_id"] != record["irp_id"]:
            raise AssertionError(f"frame {record['frame']}: no completion right after the submit")
        result.append((record, bytes.fromhex(completion["data_hex"])))
    return result


def transfer_of(submit):
    """A capture submit in the form FakeScanner records transfers."""
    if submit["transfer_type"] == "bulk":
        sha256 = submit.get("captured_sha256") or hashlib.sha256(bytes.fromhex(submit["data_hex"])).hexdigest()
        return ("bulk", submit["endpoint"], sha256)
    setup = submit["setup"]
    payload = bytes.fromhex(submit["data_hex"]) if setup["bmRequestType"] == 0x40 else setup["wLength"]
    return setup["bmRequestType"], setup["bRequest"], setup["wValue"], setup["wIndex"], payload


def bytes_from_xxd(path):
    data = bytearray()
    for line in path.read_text().splitlines():
        offset, rest = line.split(": ", 1)
        if int(offset, 16) != len(data):
            raise AssertionError(f"{path}: offset {offset} after {len(data)} bytes")
        data += bytes.fromhex(rest[:39])
    return bytes(data)


class FakeScanner:
    """Answers the requests move_carrier may send, with the Windows framing. Anything else fails the test.

    register_values maps a register to a value or to a list of values
    returned in turn (the last one repeats). fail_on is a predicate on the
    transfer tuple that makes that transfer raise "Pipe error". There is
    no read() method, so an interrupt or bulk IN read fails the test.
    """

    def __init__(self, register_values=None, bcd_device=0x0702, upload_status=b"\x02", bad_link_check_number=None,
                 bad_register_read_number=None, short_write_data=None, short_bulk=False, fail_on=None):
        values = register_values if register_values is not None else WORKING_UNIT_REGISTERS
        self.register_values = {register: list(value) if isinstance(value, list) else value
                                for register, value in values.items()}
        self.bcdDevice = bcd_device
        self.idVendor, self.idProduct, self.bus, self.address = 0x07B3, 0x1406, 1, 5
        self.upload_status = upload_status
        self.bad_link_check_number = bad_link_check_number
        self.bad_register_read_number = bad_register_read_number
        self.short_write_data = short_write_data
        self.short_bulk = short_bulk
        self.fail_on = fail_on
        self.transfers = []
        self.link_checks = 0
        self.register_reads = 0

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        payload = bytes(data_or_length) if request_type == 0x40 else data_or_length
        self.transfers.append((request_type, request, value, index, payload))
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

    def write(self, endpoint, data, timeout):
        data = bytes(data)
        self.transfers.append(("bulk", endpoint, hashlib.sha256(data).hexdigest()))
        if self.fail_on is not None and self.fail_on(self.transfers[-1]):
            raise usb.core.USBError("Pipe error")
        if endpoint != 0x02:
            raise AssertionError(f"bulk OUT to endpoint 0x{endpoint:02x}")
        return len(data) - 1 if self.short_bulk else len(data)

    def handle_write(self, value, index, data):
        if value not in (0x0083, 0x0183, 0x0082):
            raise AssertionError(f"OUT wValue 0x{value:04x}")
        if value == 0x0082 and (index, len(data)) != (0x0001, 8):
            raise AssertionError(f"buffer header wIndex 0x{index:04x}, {len(data)} bytes")
        return len(data) - 1 if data == self.short_write_data else len(data)

    def handle_read(self, value, index, length):
        if (value, index, length) == (0x008E, 0x0020, 1):
            self.link_checks += 1
            return b"\xaa" if self.link_checks == self.bad_link_check_number else b"\x55"
        if (value, index, length) == (0x008E, 0x0018, 1):
            return self.upload_status
        if value in (0x008E, 0x018E) and index & 0xFF == 0x22 and length == 2:
            self.register_reads += 1
            link = 0x00 if self.register_reads == self.bad_register_read_number else 0x55
            return bytes([self.next_register_value((index >> 8) | (value & 0x100)), link])
        raise AssertionError(f"IN wValue 0x{value:04x} wIndex 0x{index:04x}")

    def next_register_value(self, register):
        if register not in self.register_values:
            raise AssertionError(f"read of register 0x{register:02x}")
        value = self.register_values[register]
        if not isinstance(value, list):
            return value
        return value.pop(0) if len(value) > 1 else value[0]


class FakeClock:
    """Monotonic time that only sleeps advance."""

    def __init__(self, scanner):
        self.scanner = scanner
        self.now = 0.0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append((len(self.scanner.transfers), seconds))
        self.now += seconds

    def monotonic(self):
        return self.now

    def environment(self):
        return vendor_open.Environment(sleep=self.sleep, monotonic=self.monotonic, find_device=lambda: self.scanner)


def run_move(scanner, clock=None, steps=97, backscan=False, poll_limit_seconds=10.0, lamp=False, as_move_1=False):
    """Run run() and return the exit code and the log records."""
    clock = clock or FakeClock(scanner)
    log_file = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()):
        exit_code = move_carrier.run(flash_dump.Session(scanner, log_file), clock.environment(), steps, backscan,
                                     poll_limit_seconds, lamp, as_move_1)
    return exit_code, [json.loads(line) for line in log_file.getvalue().splitlines()]


def records_of_kind(records, kind):
    return [record for record in records if record["kind"] == kind]


@unittest.skipUnless(CAPTURE_PATH.exists(), CAPTURE_MISSING)
class CaptureTests(unittest.TestCase):
    def test_register_state_and_afe_write_are_the_capture_at_move_3_where_it_differs_from_the_open(self):
        at_move_3 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, START_FRAME)
        after_open = shadow_of_open()
        expected = {register: value for register, value in at_move_3.items()
                    if register not in EXCLUDED_REGISTERS | FEED_BLOCK_REGISTERS
                    and after_open.get(register) != value}
        afe = move_carrier.AFE_WRITE.sent
        sent = {**dict(move_carrier.REGISTER_STATE),
                **{afe[position]: afe[position + 1] for position in range(0, len(afe), 2)
                   if after_open.get(afe[position]) != afe[position + 1]}}
        self.assertEqual(sent, expected)
        self.assertEqual(move_carrier.REGISTER_STATE, tuple(sorted((register, value) for register, value in
                                                                   expected.items() if register not in AFE_REGISTERS)))

    def test_register_state_at_the_start_write_differs_from_the_capture_only_in_the_lamp(self):
        scanner = FakeScanner()
        self.assertEqual(run_move(scanner)[0], move_carrier.EXIT_GOOD)
        start = scanner.transfers.index(write_transfer("0f01"))
        at_start = replay_register_writes(shadow_of_open(), scanner.transfers[:start + 1])
        at_move_3 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, START_FRAME)
        differing = {register: (at_start.get(register), at_move_3.get(register))
                     for register in set(at_start) | set(at_move_3)
                     if at_start.get(register) != at_move_3.get(register)}
        self.assertEqual(differing, {0x03: (0x00, 0x30)})

    def test_register_state_with_the_lamp_as_captured_matches_the_capture_in_full(self):
        scanner = FakeScanner()
        self.assertEqual(run_move(scanner, lamp=True)[0], move_carrier.EXIT_GOOD)
        start = scanner.transfers.index(write_transfer("0f01"))
        at_start = replay_register_writes(shadow_of_open(), scanner.transfers[:start + 1])
        at_move_3 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, START_FRAME)
        self.assertEqual({register: at_start.get(register) for register in at_move_3}, at_move_3)

    def test_afe_write_is_frame_6175(self):
        submit = capture_records(CAPTURE_PATH, 6175, 6175)[0]
        self.assertEqual(transfer_of(submit), write_transfer(move_carrier.AFE_WRITE.sent.hex()))

    def test_cut_writes_are_frames_6287_and_6291(self):
        submits = [record for record in capture_records(CAPTURE_PATH, 6287, 6294) if record["event"] == "submit"]
        self.assertEqual([transfer_of(submit) for submit in submits],
                         [write_transfer(move_carrier.CUT_MOTOR_POWER.sent.hex()), LINK_CHECK_TRANSFER,
                          write_transfer(move_carrier.CUT_FEEDL.sent.hex()), LINK_CHECK_TRANSFER])

    def test_feed_block_registers_are_those_of_frame_6463(self):
        records = capture_records(CAPTURE_PATH, 6463, 6463)
        self.assertEqual(bytes.fromhex(records[0]["data_hex"]), move_carrier.feed_block(97).sent)
        self.assertEqual(set(move_carrier.feed_block(97).sent[0::2]), FEED_BLOCK_REGISTERS)

    def test_a_run_sends_move_3_of_the_capture_byte_for_byte(self):
        captured = submits_with_answers(capture_records(CAPTURE_PATH, MOVE_FIRST_FRAME, MOVE_LAST_FRAME))
        polls = [answer[0] for submit, answer in captured if 6487 <= submit["frame"] <= 6628]
        self.assertEqual(polls, MOVE_3_POLLS)
        scanner = FakeScanner({**WORKING_UNIT_REGISTERS, 0x101: [0xF4] + polls + [0xF4]})
        self.assertEqual(run_move(scanner)[0], move_carrier.EXIT_GOOD)
        expected = [transfer_of(submit) for submit, _ in captured]
        self.assertEqual(captured[0][0]["frame"], 6445)
        self.assertEqual(scanner.transfers[MOVE_START:MOVE_START + len(expected)], expected)
        self.assertEqual(scanner.transfers[MOVE_START + len(expected):MOVE_START + len(expected) + 2],
                         [write_transfer("0208"), LINK_CHECK_TRANSFER])

    def test_captured_answers_match_the_working_unit(self):
        captured = dict((submit["frame"], answer) for submit, answer in
                        submits_with_answers(capture_records(CAPTURE_PATH, MOVE_FIRST_FRAME, MOVE_LAST_FRAME)))
        for read in (move_carrier.BEFORE_READ_0X33, move_carrier.AFTER_READ_0X33, move_carrier.AFTER_READ_0X101):
            with self.subTest(frame=read.frame):
                self.assertEqual(captured[read.frame], bytes([read.captured, 0x55]))
        for request in (upload[2] for upload in move_carrier.TABLE_UPLOADS):
            with self.subTest(frame=request.frame):
                self.assertEqual(captured[request.frame], request.captured)


class TableTests(unittest.TestCase):
    def test_slope_table_equals_the_hex_dump(self):
        self.assertEqual(move_carrier.SLOPE_TABLE, bytes_from_xxd(TABLES_DIRECTORY / "slope-6353.hex"))
        for _, upload, _ in move_carrier.TABLE_UPLOADS:
            self.assertEqual(upload.sent, move_carrier.SLOPE_TABLE)

    def test_slope_table_hash_is_the_one_in_the_tables_readme(self):
        readme = (TABLES_DIRECTORY / "README.md").read_text()
        row = next(line for line in readme.splitlines() if line.startswith("| `slope-6353.hex`"))
        match = re.search(r"`([0-9a-f]{64})`", row)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1), move_carrier.SLOPE_TABLE_SHA256)
        self.assertEqual(TABLE_SHA256, move_carrier.SLOPE_TABLE_SHA256)
        self.assertEqual(len(move_carrier.SLOPE_TABLE), 512)

    def test_register_state_is_ascending_and_leaves_out_the_excluded_and_afe_registers(self):
        registers = [register for register, _ in move_carrier.REGISTER_STATE]
        self.assertEqual(registers, sorted(set(registers)))
        self.assertFalse(set(registers) & (EXCLUDED_REGISTERS | FEED_BLOCK_REGISTERS | AFE_REGISTERS))
        self.assertEqual(len(registers), 76)

    def test_register_state_differs_from_the_open_in_every_register(self):
        after_open = shadow_of_open()
        for register, value in move_carrier.REGISTER_STATE:
            with self.subTest(register=f"{register:02x}"):
                self.assertNotEqual(after_open.get(register), value)

    def test_register_state_goes_in_transfers_of_at_most_32_pairs(self):
        writes = move_carrier.REGISTER_STATE_WRITES
        self.assertEqual([len(request.sent) // 2 for request in writes], [32, 32, 12])
        self.assertEqual({(request.request, request.value, request.index) for request in writes}, {(0x04, 0x0083, 0)})
        self.assertEqual(b"".join(request.sent for request in writes), bytes.fromhex(
            pairs_hex(move_carrier.REGISTER_STATE)))

    def test_registers_from_0x100_go_last_through_wvalue_0x0183(self):
        writes = move_carrier.register_state_writes(((0x115, 0x80), (0x05, 0xC8), (0x114, 0x80), (0x04, 0x42)))
        self.assertEqual([(request.value, request.sent) for request in writes],
                         [(0x0083, bytes.fromhex("0442 05c8")), (0x0183, bytes.fromhex("1480 1580"))])

    def test_feed_block_sets_feedl_big_endian(self):
        self.assertEqual(move_carrier.feed_block(97).sent, bytes.fromhex(FEED_BLOCK_97))
        self.assertEqual(move_carrier.feed_block(97).frame, 6463)
        for steps, feedl in ((1, "000001"), (980, "0003d4"), (1000, "0003e8")):
            with self.subTest(steps=steps):
                self.assertEqual(move_carrier.feed_block(steps).sent[2:8], bytes.fromhex(
                    f"3d{feedl[0:2]} 3e{feedl[2:4]} 3f{feedl[4:6]}"))
        for steps in (0, -1, 1001, 0x1000000):
            with self.subTest(steps=steps):
                with self.assertRaises(PermissionError):
                    move_carrier.feed_block(steps)

    def test_read_registers_are_ones_vendor_open_may_read(self):
        self.assertTrue(set(move_carrier.LOGGED_REGISTERS) <= set(vendor_open.LOGGED_REGISTERS))


class MoveTests(unittest.TestCase):
    def test_working_unit_run_sends_the_listed_requests_and_exits_zero(self):
        scanner = FakeScanner()
        exit_code, records = run_move(scanner)
        self.assertEqual(exit_code, move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_transfers())
        move_end = records_of_kind(records, "move_end")[0]
        self.assertEqual((move_end["motorenb_cleared_within_limit"], move_end["cut_sent"],
                          move_end["motorenb_cleared_after_cut"]), (True, False, None))
        self.assertEqual(records_of_kind(records, "registers_before")[0]["0x36"], "fe")
        self.assertEqual(records_of_kind(records, "registers_after")[0]["0x02"], "08")

    def test_owner_unit_after_the_open_gets_0x33_reset_to_0x1c_first(self):
        scanner = FakeScanner(OWNER_UNIT_REGISTERS)
        exit_code, records = run_move(scanner)
        self.assertEqual(exit_code, move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_transfers(polls=5))
        self.assertEqual(records_of_kind(records, "registers_before")[0]["0x33"], "0e")
        reads = {record["frame"]: record for record in records_of_kind(records, "register_read")}
        self.assertEqual((reads[6449]["received"], reads[6449]["captured"], reads[6449]["differs"]),
                         ("1c", "1c", False))

    def test_later_0x33_writes_keep_the_read_value_except_bit_5(self):
        scanner = FakeScanner({**WORKING_UNIT_REGISTERS, 0x33: [0x0E, 0x3E, 0x1E, 0x1E]})
        exit_code, records = run_move(scanner)
        self.assertEqual(exit_code, move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_transfers(register_33_before=0x3E, register_33_after=0x1E))
        reads = {record["frame"]: record for record in records_of_kind(records, "register_read")}
        self.assertEqual((reads[6449]["received"], reads[6449]["differs"]), ("3e", True))

    def test_backscan_sets_0x09_before_the_block_and_clears_it_right_after_the_polls(self):
        scanner = FakeScanner()
        self.assertEqual(run_move(scanner, backscan=True)[0], move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_transfers(backscan=True))

    def test_steps_set_feedl(self):
        scanner = FakeScanner()
        self.assertEqual(run_move(scanner, steps=1000)[0], move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_transfers(feedl_hex="0003e8"))

    def test_lamp_as_captured_writes_0x03_after_the_afe_write_and_switches_it_off_after_motor_power(self):
        scanner = FakeScanner()
        exit_code, records = run_move(scanner, lamp=True)
        self.assertEqual(exit_code, move_carrier.EXIT_GOOD)
        afe = scanner.transfers.index(write_transfer(move_carrier.AFE_WRITE.sent.hex()))
        self.assertEqual(scanner.transfers[afe + 2:afe + 4], [write_transfer("0330"), LINK_CHECK_TRANSFER])
        motor_off = len(scanner.transfers) - 1 - scanner.transfers[::-1].index(write_transfer("0208"))
        self.assertEqual(scanner.transfers[motor_off + 2:motor_off + 4], [write_transfer("0300"), LINK_CHECK_TRANSFER])
        self.assertEqual(scanner.transfers.count(write_transfer("0330")), 1)
        self.assertEqual(scanner.transfers.count(write_transfer("0300")), 1)
        self.assertEqual(records_of_kind(records, "lamp_write")[0]["sent"], "03 30")
        without_lamp = FakeScanner()
        run_move(without_lamp)
        lamp_transfers_removed = (scanner.transfers[:afe + 2] + scanner.transfers[afe + 4:motor_off + 2]
                                  + scanner.transfers[motor_off + 4:])
        self.assertEqual(lamp_transfers_removed, without_lamp.transfers)

    def test_polls_every_15_ms_from_the_start_and_logs_each_value(self):
        scanner = FakeScanner(OWNER_UNIT_REGISTERS)
        clock = FakeClock(scanner)
        _, records = run_move(scanner, clock)
        polls = records_of_kind(records, "poll")
        self.assertEqual([poll["seconds_since_start"] for poll in polls], [0.0, 0.015, 0.03, 0.045, 0.06])
        self.assertEqual([(poll["phase"], poll["0x101"], poll["homesnr"], poll["motorenb"]) for poll in polls],
                         [("move", "dd", True, True), ("move", "d5", False, True), ("move", "d5", False, True),
                          ("move", "f5", False, True), ("move", "f4", False, False)])
        start_link_check = MOVE_START + move_transfers(polls=0).index(write_transfer("0f01")) + 1
        self.assertEqual(scanner.transfers[start_link_check - 1:start_link_check + 1],
                         [write_transfer("0f01"), LINK_CHECK_TRANSFER])
        self.assertEqual([count for count, _ in clock.sleeps], [start_link_check + 1 + poll for poll in range(1, 5)])
        for _, seconds in clock.sleeps:
            self.assertAlmostEqual(seconds, 0.015)

    def test_timeout_cuts_the_move_then_polls_until_motorenb_clears_and_exits_23(self):
        scanner = FakeScanner({**WORKING_UNIT_REGISTERS, 0x101: [0xF4] + [0xD5] * 8 + [0xF5, 0xF5, 0xF4]})
        exit_code, records = run_move(scanner, poll_limit_seconds=0.1)
        self.assertEqual(exit_code, move_carrier.EXIT_MOTOR_TIMEOUT)
        self.assertEqual(exit_code, 23)
        polls = records_of_kind(records, "poll")
        self.assertEqual([poll["phase"] for poll in polls], ["move"] * 8 + ["after_cut"] * 3)
        self.assertTrue(polls[6]["seconds_since_start"] < 0.1 <= polls[7]["seconds_since_start"])
        self.assertAlmostEqual(polls[8]["seconds_since_start"], polls[7]["seconds_since_start"])
        cut_writes = [record["frame"] for record in records_of_kind(records, "register_write")
                      if record["frame"] in (6287, 6291)]
        self.assertEqual(cut_writes, [6287, 6291])
        move_end = records_of_kind(records, "move_end")[0]
        self.assertEqual((move_end["motorenb_cleared_within_limit"], move_end["cut_sent"],
                          move_end["motorenb_cleared_after_cut"]), (False, True, True))
        self.assertEqual(scanner.transfers, run_transfers(polls=8, polls_after_cut=3))

    def test_motorenb_still_set_5_seconds_after_the_cut_still_ends_with_motor_power_off(self):
        scanner = FakeScanner({**WORKING_UNIT_REGISTERS, 0x101: [0xF4, 0xD5]})
        exit_code, records = run_move(scanner, poll_limit_seconds=0.1)
        self.assertEqual(exit_code, move_carrier.EXIT_MOTOR_TIMEOUT)
        after_cut = [poll for poll in records_of_kind(records, "poll") if poll["phase"] == "after_cut"]
        self.assertEqual(len(after_cut), 335)
        cut_at = after_cut[0]["seconds_since_start"]
        self.assertTrue(after_cut[-2]["seconds_since_start"] - cut_at < 5.0
                        <= after_cut[-1]["seconds_since_start"] - cut_at)
        self.assertEqual(records_of_kind(records, "move_end")[0]["motorenb_cleared_after_cut"], False)
        self.assertEqual(scanner.transfers, run_transfers(polls=8, polls_after_cut=335))

    def test_every_request_is_logged(self):
        scanner = FakeScanner()
        _, records = run_move(scanner)
        request_kinds = {"register_state_write", "register_write", "register_read", "buffer_header", "bulk_write",
                         "upload_status_read", "link_check", "poll"}
        logged = len([record for record in records if record["kind"] in request_kinds])
        summaries = len(records_of_kind(records, "registers_before") + records_of_kind(records, "registers_after"))
        self.assertEqual(logged + summaries * len(LOGGED_READ_TRANSFERS), len(scanner.transfers))
        uploads = records_of_kind(records, "bulk_write")
        self.assertEqual([(upload["frame"], upload["sha256"], upload["length"]) for upload in uploads],
                         [(6471, TABLE_SHA256, 512), (6479, TABLE_SHA256, 512)])


class GateTests(unittest.TestCase):
    def test_unfinished_open_or_enabled_motor_sends_no_write_and_exits_22(self):
        cases = ((0x4C, 0xFE, "PWRBIT clear"), (0xDD, 0xFE, "MOTORENB set"), (0x0D, 0xFE, "PWRBIT clear"),
                 (0xDC, 0xFC, "0x36 is not 0xfe"), (0xDC, 0x00, "0x36 is not 0xfe"))
        for status, output_enable, reason in cases:
            with self.subTest(status=f"{status:02x}", output_enable=f"{output_enable:02x}"):
                scanner = FakeScanner({**OWNER_UNIT_REGISTERS, 0x101: status, 0x36: output_enable})
                exit_code, records = run_move(scanner)
                self.assertEqual(exit_code, move_carrier.EXIT_OPEN_NOT_SENT)
                self.assertEqual(exit_code, 22)
                self.assertEqual(scanner.transfers, LOGGED_READ_TRANSFERS)
                refused = records_of_kind(records, "refused")[0]
                self.assertEqual((refused["0x101"], refused["0x36"]), (f"{status:02x}", f"{output_enable:02x}"))
                self.assertIn(reason, refused["reason"])

    def test_gate_values(self):
        for status in (0xDC, 0xF4, 0xF8, 0x80):
            self.assertEqual(move_carrier.gate_refusal_reasons({0x101: status, 0x36: 0xFE}), [])
        for status in (0x4C, 0x00, 0xDD, 0xD5, 0x81):
            self.assertNotEqual(move_carrier.gate_refusal_reasons({0x101: status, 0x36: 0xFE}), [])
        self.assertEqual(len(move_carrier.gate_refusal_reasons({0x101: 0x0D, 0x36: 0xFC})), 3)


class ErrorTests(unittest.TestCase):
    def assert_stopped_after(self, scanner, last_transfer, **move_arguments):
        exit_code, records = run_move(scanner, **move_arguments)
        self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
        self.assertEqual(len(records_of_kind(records, "error")), 1)
        self.assertEqual(scanner.transfers[-1], last_transfer)
        return records

    def test_bad_link_check_stops_the_run(self):
        scanner = FakeScanner(bad_link_check_number=2)
        self.assert_stopped_after(scanner, LINK_CHECK_TRANSFER)
        self.assertEqual(len(scanner.transfers), len(LOGGED_READ_TRANSFERS) + 4)

    def test_upload_status_other_than_0x02_stops_before_the_start(self):
        scanner = FakeScanner(upload_status=b"\x00")
        self.assert_stopped_after(scanner, UPLOAD_STATUS_TRANSFER)
        self.assertNotIn(write_transfer("0f01"), scanner.transfers)
        self.assertEqual(scanner.transfers.count(TABLE_TRANSFER), 1)

    def test_short_bulk_write_stops_before_the_start(self):
        scanner = FakeScanner(short_bulk=True)
        records = self.assert_stopped_after(scanner, TABLE_TRANSFER)
        self.assertEqual(records_of_kind(records, "error")[0]["frame"], 6471)
        self.assertNotIn(write_transfer("0f01"), scanner.transfers)

    def test_short_write_names_its_frame(self):
        scanner = FakeScanner(short_write_data=bytes.fromhex("0258"))
        records = self.assert_stopped_after(scanner, write_transfer("0258"))
        error = records_of_kind(records, "error")[0]
        self.assertEqual((error["frame"], error["request"]), (6451, "register_write"))

    def test_usb_error_during_the_polls_stops_the_run(self):
        poll_count = 0

        def third_poll(transfer):
            nonlocal poll_count
            if transfer == read_transfer(0x101) and write_transfer("0f01") in scanner.transfers:
                poll_count += 1
            return poll_count == 3

        scanner = FakeScanner(fail_on=third_poll)
        records = self.assert_stopped_after(scanner, read_transfer(0x101))
        self.assertEqual(scanner.transfers.count(read_transfer(0x101)), 1 + 3)
        self.assertEqual(records_of_kind(records, "error")[0]["request"], "poll_move")

    def test_poll_without_0x55_stops_the_run(self):
        reads_before_polls = len(LOGGED_READ_TRANSFERS) + 1
        scanner = FakeScanner(bad_register_read_number=reads_before_polls + 2)
        self.assert_stopped_after(scanner, read_transfer(0x101))

    def test_table_hash_mismatch_of_a_sent_payload_sends_nothing_and_exits_24(self):
        for upload_number, table in ((0, bytes(512)), (1, move_carrier.SLOPE_TABLE[:-1] + b"\x00"),
                                     (1, move_carrier.SLOPE_TABLE + b"\x00")):
            with self.subTest(upload_number=upload_number, length=len(table)):
                uploads = list(move_carrier.TABLE_UPLOADS)
                header, upload, status = uploads[upload_number]
                uploads[upload_number] = (header, dataclasses.replace(upload, sent=table), status)
                scanner = FakeScanner()
                with unittest.mock.patch.object(move_carrier, "TABLE_UPLOADS", tuple(uploads)):
                    exit_code, records = run_move(scanner)
                self.assertEqual(exit_code, move_carrier.EXIT_TABLE_HASH)
                self.assertEqual(exit_code, 24)
                self.assertEqual(scanner.transfers, [])
                self.assertIn(move_carrier.SLOPE_TABLE_SHA256, records_of_kind(records, "refused")[0]["reason"])


def assert_refused(test_case, request, plan):
    """The request raises PermissionError in transfer() and never reaches the device."""
    scanner = FakeScanner()
    with test_case.assertRaises(PermissionError):
        move_carrier.transfer(flash_dump.Session(scanner, io.StringIO()), plan, request)
    test_case.assertEqual(scanner.transfers, [])


class SafetyTests(unittest.TestCase):
    def refused(self, request, plan=None):
        assert_refused(self, request, plan or move_carrier.MovePlan(97, False))

    def test_requests_outside_the_move_never_reach_the_device(self):
        refused = [
            move_carrier.single_write(6483, 0x0F, 0x02),
            move_carrier.single_write(6463, 0x02, 0x18),
            move_carrier.single_write(6463, 0x02, 0x78),
            move_carrier.single_write(0, 0x03, 0x30),
            move_carrier.single_write(0, 0x01, 0x23),
            move_carrier.single_write(0, 0x5E, 0x2A),
            move_carrier.register_write(6175, bytes.fromhex("5104 5d00 5e2b")),
            move_carrier.register_write(6291, bytes.fromhex("3d00 3e00 3f02")),
            move_carrier.feed_block(98),
            move_carrier.register_write(None, move_carrier.START.sent + move_carrier.MOTOR_POWER_OFF.sent),
            dataclasses.replace(move_carrier.REGISTER_STATE_WRITES[0],
                                sent=move_carrier.REGISTER_STATE_WRITES[0].sent[:-1] + b"\x00"),
            move_carrier.buffer_header(6467, 0x10000000, len(move_carrier.SLOPE_TABLE)),
            dataclasses.replace(move_carrier.TABLE_UPLOADS[0][1], sent=bytes(512)),
            dataclasses.replace(move_carrier.TABLE_UPLOADS[0][1], endpoint=0x01),
            move_carrier.Request("register_read", None, 0xC0, 0x04, 0x008E, 0x0F22, length=2),
            move_carrier.Request("flash_write", 67, 0x40, 0x04, 0x008B, 0x000B, bytes(4)),
            move_carrier.Request("flash_read", 71, 0xC0, 0x04, 0x008A, 0x000F, length=64),
            move_carrier.Request("vendor_read", 125, 0xC0, 0x0C, 0x008E, 0x0000, length=1),
        ]
        for request in refused:
            with self.subTest(request=request.kind, sent=request.sent[:8].hex()):
                self.refused(request)

    def test_reads_of_other_registers_are_refused(self):
        scanner = FakeScanner()
        for register in (0x0F, 0x34, 0x100, 0x06):
            with self.subTest(register=f"{register:02x}"):
                with self.assertRaises(PermissionError):
                    move_carrier.read_register(flash_dump.Session(scanner, io.StringIO()), register, "test", None)
        self.assertEqual(scanner.transfers, [])

    def test_backscan_writes_need_the_flag(self):
        for request in (move_carrier.BACKSCAN_SET, move_carrier.BACKSCAN_CLEAR):
            with self.subTest(sent=request.sent.hex()):
                self.refused(request)
                move_carrier.check_allowed(request, move_carrier.MovePlan(97, True))

    def test_lamp_writes_need_the_flag(self):
        for request in (move_carrier.LAMP_AS_CAPTURED, move_carrier.LAMP_OFF):
            with self.subTest(sent=request.sent.hex()):
                self.refused(request)
                move_carrier.check_allowed(request, move_carrier.MovePlan(97, False, lamp=True))
        self.refused(move_carrier.single_write(0, 0x03, 0x10), move_carrier.MovePlan(97, False, lamp=True))

    def test_0x33_writes_are_the_fixed_reset_or_change_only_bit_5_of_the_last_read(self):
        move_carrier.check_allowed(move_carrier.REGISTER_33_RESET, move_carrier.MovePlan(97, False))
        self.refused(move_carrier.register_33_write(6459, 0x3C))
        plan = move_carrier.MovePlan(97, False, register_33_read=0x0E)
        for allowed in (0x2E, 0x0E, 0x1C):
            move_carrier.check_allowed(move_carrier.register_33_write(6459, allowed), plan)
        for value in (0x3C, 0x1E, 0x00, 0x3E, 0x8E):
            with self.subTest(value=f"{value:02x}"):
                self.refused(move_carrier.register_33_write(6459, value), plan)

    def test_feed_block_must_have_the_steps_of_the_run(self):
        move_carrier.check_allowed(move_carrier.feed_block(500), move_carrier.MovePlan(500, False))
        self.refused(move_carrier.feed_block(97), move_carrier.MovePlan(500, False))
        for steps in (0, 1001):
            with self.subTest(steps=steps):
                self.refused(move_carrier.LINK_CHECK, move_carrier.MovePlan(steps, False))

    def test_every_transfer_of_a_run_is_checked(self):
        for registers, poll_limit_seconds in ((WORKING_UNIT_REGISTERS, 10.0),
                                              ({**WORKING_UNIT_REGISTERS, 0x101: [0xF4, 0xD5]}, 0.1)):
            with self.subTest(poll_limit_seconds=poll_limit_seconds):
                scanner = FakeScanner(registers)
                with unittest.mock.patch.object(move_carrier, "check_allowed",
                                                wraps=move_carrier.check_allowed) as check, \
                        unittest.mock.patch.object(vendor_open, "read_register",
                                                   wraps=vendor_open.read_register) as read:
                    run_move(scanner, backscan=True, poll_limit_seconds=poll_limit_seconds)
                self.assertEqual(check.call_count + read.call_count, len(scanner.transfers))


class RefusalTests(unittest.TestCase):
    OWN_PID = 300

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = pathlib.Path(directory.name)
        self.probe_disabled = self.directory / "probe-disabled"
        self.probe_disabled.touch()
        self.proc_root = self.directory / "proc"
        self.proc_root.mkdir()
        # This run as the Pi starts it: ssh's shell, sudo, sudo's monitor, then Python.
        tool = b"/home/pi/plustek-preservation/move_carrier.py"
        self.add_process(297, [b"bash", b"-c", b"sudo venv/bin/python " + tool + b" scanner-log/move"], parent=1)
        self.add_process(298, [b"sudo", b"venv/bin/python", tool, b"scanner-log/move"], parent=297)
        self.add_process(299, [b"sudo", b"venv/bin/python", tool, b"scanner-log/move"], parent=298)
        self.add_process(self.OWN_PID, [b"venv/bin/python", tool, b"scanner-log/move"], parent=299)

    def add_process(self, pid, arguments, parent=1):
        (self.proc_root / str(pid)).mkdir()
        (self.proc_root / str(pid) / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")
        (self.proc_root / str(pid) / "stat").write_text(f"{pid} (some (name)) S {parent} {pid} {pid} 0 -1\n")

    def refusal(self, device):
        return move_carrier.refusal_exit_code(self.probe_disabled, self.proc_root, self.OWN_PID, device)

    def test_good_start_with_its_own_process_chain(self):
        self.add_process(100, [b"/bin/sh", b"./watch-scanner.sh"])
        self.assertIsNone(self.refusal(FakeScanner()))
        self.assertEqual(move_carrier.own_process_chain(self.proc_root, self.OWN_PID), {297, 298, 299, 300, 1})

    def test_missing_probe_disabled_is_exit_16(self):
        self.probe_disabled.unlink()
        self.assertEqual(self.refusal(FakeScanner()), flash_dump.EXIT_PROBE_ACTIVE)

    def test_another_scanner_tool_running_is_exit_16(self):
        for pid, script in enumerate((b"probe_readonly.py", b"keep_awake.py", b"vendor_open.py", b"flash_dump.py",
                                      b"eeprom_read.py", b"move_carrier.py", b"snapshot.py"), start=400):
            with self.subTest(script=script):
                self.add_process(pid, [b"sudo", b"/home/pi/plustek-preservation/venv/bin/python",
                                       b"/home/pi/plustek-preservation/" + script])
                self.assertEqual(self.refusal(FakeScanner()), flash_dump.EXIT_PROBE_ACTIVE)
                for name in ("cmdline", "stat"):
                    (self.proc_root / str(pid) / name).unlink()
                (self.proc_root / str(pid)).rmdir()

    def test_no_scanner_is_exit_10(self):
        self.assertEqual(self.refusal(None), flash_dump.EXIT_NOT_FOUND)

    def test_other_bcd_device_is_exit_19(self):
        self.assertEqual(self.refusal(FakeScanner(bcd_device=0x0701)), move_carrier.EXIT_WRONG_CHIP)


class ArgumentTests(unittest.TestCase):
    def test_steps(self):
        for text, steps in (("1", 1), ("97", 97), ("1000", 1000)):
            self.assertEqual(move_carrier.steps_argument(text), steps)
        for text in ("0", "-1", "1001"):
            with self.assertRaises(argparse.ArgumentTypeError):
                move_carrier.steps_argument(text)
        with self.assertRaises(ValueError):
            move_carrier.steps_argument("ninety")

    def test_poll_limit(self):
        self.assertEqual(move_carrier.poll_limit_argument("10"), 10.0)
        self.assertEqual(move_carrier.poll_limit_argument("2.5"), 2.5)
        for text in ("0", "-1", "inf", "nan"):
            with self.subTest(text=text):
                with self.assertRaises(argparse.ArgumentTypeError):
                    move_carrier.poll_limit_argument(text)

    def test_command_line(self):
        parser = move_carrier.argument_parser()
        defaults = parser.parse_args(["logs"])
        self.assertEqual((defaults.steps, defaults.backscan, defaults.poll_limit_seconds), (97, False, 10.0))
        chosen = parser.parse_args(["logs", "--steps", "200", "--backscan", "--poll-limit-seconds", "4"])
        self.assertEqual((chosen.steps, chosen.backscan, chosen.poll_limit_seconds), (200, True, 4.0))
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["logs", "--steps", "1001"])

    def test_exit_codes(self):
        self.assertEqual((move_carrier.EXIT_GOOD, flash_dump.EXIT_NOT_FOUND, move_carrier.EXIT_USB_ERROR,
                          move_carrier.EXIT_PROBE_ACTIVE, move_carrier.EXIT_WRONG_CHIP,
                          move_carrier.EXIT_OPEN_NOT_SENT, move_carrier.EXIT_MOTOR_TIMEOUT,
                          move_carrier.EXIT_TABLE_HASH),
                         (0, 10, 13, 16, 19, 22, 23, 24))
        self.assertNotIn(move_carrier.EXIT_OPEN_NOT_SENT, (vendor_open.EXIT_DROPPED, vendor_open.EXIT_CARRIER_NOT_HOME))


@unittest.skipUnless(CAPTURE_PATH.exists(), CAPTURE_MISSING)
class MoveOneCaptureTests(unittest.TestCase):
    def test_register_state_and_afe_write_are_the_capture_at_move_1_where_it_differs_from_the_open(self):
        at_move_1 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, MOVE_1_START_FRAME)
        after_open = shadow_of_open()
        expected = {register: value for register, value in at_move_1.items()
                    if register not in MOVE_1_EXCLUDED_REGISTERS | MOVE_1_BLOCK_REGISTERS
                    and after_open.get(register) != value}
        afe = move_carrier.AFE_WRITE.sent
        sent = {**dict(move_carrier.REGISTER_STATE_MOVE_1),
                **{afe[position]: afe[position + 1] for position in range(0, len(afe), 2)
                   if after_open.get(afe[position]) != afe[position + 1]}}
        self.assertEqual(sent, expected)
        self.assertEqual(move_carrier.REGISTER_STATE_MOVE_1, tuple(sorted(
            (register, value) for register, value in expected.items() if register not in AFE_REGISTERS)))

    def test_register_state_at_the_start_write_equals_the_capture_except_feedl(self):
        scanner = FakeScanner(WORKING_UNIT_MOVE_1_REGISTERS)
        self.assertEqual(run_move(scanner, as_move_1=True)[0], move_carrier.EXIT_GOOD)
        start = scanner.transfers.index(write_transfer("0f01"))
        at_start = replay_register_writes(shadow_of_open(), scanner.transfers[:start + 1])
        at_move_1 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, MOVE_1_START_FRAME)
        differing = {register: (at_start.get(register), at_move_1.get(register))
                     for register in set(at_start) | set(at_move_1)
                     if at_start.get(register) != at_move_1.get(register)}
        self.assertEqual(differing, {0x3E: (0x00, 0x27), 0x3F: (0x61, 0xAE)})  # FEEDL 97 against 10158

    def test_capture_state_at_move_1_and_move_3_differs_in_0x33_feedl_and_fmovno(self):
        at_move_1 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, MOVE_1_START_FRAME)
        at_move_3 = shadow_of_capture(CAPTURE_PATH, FIRST_FRAME, START_FRAME)
        differing = {register: (at_move_1.get(register), at_move_3.get(register))
                     for register in set(at_move_1) | set(at_move_3)
                     if at_move_1.get(register) != at_move_3.get(register)}
        self.assertEqual(differing, {0x33: (0x1C, 0x3C), 0x3E: (0x27, 0x00), 0x3F: (0xAE, 0x61),
                                     0xAF: (0x7F, 0xFF)})

    def test_from_6257_to_the_start_the_vendor_writes_only_the_block_and_the_start(self):
        submits = [record for record in capture_records(CAPTURE_PATH, 6257, MOVE_1_START_FRAME)
                   if record["event"] == "submit"]
        register_writes = [transfer_of(submit) for submit in submits if submit["transfer_type"] == "control"
                           and submit["setup"]["bmRequestType"] == 0x40 and submit["setup"]["wValue"] == 0x83]
        self.assertEqual(register_writes, [write_transfer(MOVE_1_BLOCK_10158.replace(" ", "")),
                                           write_transfer("0f01")])
        self.assertEqual([submit["transfer_type"] for submit in submits if submit["transfer_type"] == "interrupt"],
                         ["interrupt"])
        self.assertEqual(move_carrier.MOVE_1_BLOCK_CAPTURED, bytes.fromhex(MOVE_1_BLOCK_10158))

    def test_last_writes_of_0x33_and_0x0a_before_move_1(self):
        last_writes = {}
        for record in capture_records(CAPTURE_PATH, FIRST_FRAME, MOVE_1_START_FRAME):
            setup = record.get("setup", {})
            if record["event"] == "submit" and setup.get("bmRequestType") == 0x40 and setup["wValue"] == 0x0083:
                data = bytes.fromhex(record["data_hex"])
                for position in range(0, len(data), 2):
                    last_writes[data[position]] = (record["frame"], data[position + 1])
        self.assertEqual(last_writes[0x33], (6085, 0x1C))
        self.assertEqual(last_writes[0x0A], (6189, 0x48))
        self.assertEqual(move_carrier.REGISTER_33_BEFORE_MOVE_1.frame, 6085)

    def test_a_move_1_run_sends_frames_6259_to_6283_with_its_feedl(self):
        captured = submits_with_answers(capture_records(CAPTURE_PATH, 6259, 6284))
        expected = [transfer_of(submit) for submit, _ in captured]
        expected[0] = write_transfer(MOVE_1_BLOCK_10158.replace("3d00 3e27 3fae", "3d00 3e00 3f61"))
        self.assertEqual(captured[-1][0]["frame"], 6283)
        scanner = FakeScanner(WORKING_UNIT_MOVE_1_REGISTERS)
        self.assertEqual(run_move(scanner, as_move_1=True)[0], move_carrier.EXIT_GOOD)
        block_index = MOVE_1_START + 2
        self.assertEqual(scanner.transfers[block_index:block_index + len(expected)], expected)
        self.assertEqual(captured[-1][1], bytes([0xDD, 0x55]))

    def test_captured_answers_match_the_working_unit(self):
        captured = dict((submit["frame"], answer) for submit, answer in
                        submits_with_answers(capture_records(CAPTURE_PATH, 6259, 6330)))
        read = move_carrier.MOVE_1_READ_0X101
        self.assertEqual(captured[read.frame], bytes([read.captured, 0x55]))
        for request in (upload[2] for upload in move_carrier.TABLE_UPLOADS_MOVE_1):
            with self.subTest(frame=request.frame):
                self.assertEqual(captured[request.frame], request.captured)


class MoveOneTests(unittest.TestCase):
    def test_slope_table_equals_the_hex_dump_and_the_readme_hash(self):
        self.assertEqual(move_carrier.SLOPE_TABLE_MOVE_1, bytes_from_xxd(TABLES_DIRECTORY / "slope-6267.hex"))
        for _, upload, _ in move_carrier.TABLE_UPLOADS_MOVE_1:
            self.assertEqual(upload.sent, move_carrier.SLOPE_TABLE_MOVE_1)
        readme = (TABLES_DIRECTORY / "README.md").read_text()
        row = next(line for line in readme.splitlines() if line.startswith("| `slope-6267.hex`"))
        match = re.search(r"`([0-9a-f]{64})`", row)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1), move_carrier.SLOPE_TABLE_MOVE_1_SHA256)
        self.assertEqual(MOVE_1_TABLE_SHA256, move_carrier.SLOPE_TABLE_MOVE_1_SHA256)

    def test_register_state_shape(self):
        registers = [register for register, _ in move_carrier.REGISTER_STATE_MOVE_1]
        self.assertEqual(registers, sorted(set(registers)))
        self.assertFalse(set(registers) & (MOVE_1_EXCLUDED_REGISTERS | MOVE_1_BLOCK_REGISTERS | AFE_REGISTERS))
        self.assertEqual(len(registers), 74)
        self.assertEqual([len(request.sent) // 2 for request in move_carrier.REGISTER_STATE_MOVE_1_WRITES],
                         [32, 32, 10])
        after_open = shadow_of_open()
        for register, value in move_carrier.REGISTER_STATE_MOVE_1:
            with self.subTest(register=f"{register:02x}"):
                self.assertNotEqual(after_open.get(register), value)

    def test_the_two_state_tables_differ_only_in_what_the_blocks_write(self):
        move_1 = dict(move_carrier.REGISTER_STATE_MOVE_1)
        move_3 = dict(move_carrier.REGISTER_STATE)
        self.assertEqual({register: value for register, value in move_1.items() if register not in move_3},
                         {0x8A: 0x00, 0x8B: 0x55, 0x8C: 0x00, 0x8D: 0x00, 0x8E: 0x55, 0x8F: 0x00, 0x90: 0x01,
                          0x91: 0x54, 0x92: 0x00})
        self.assertTrue(set(move_1) - set(move_3) <= FEED_BLOCK_REGISTERS)
        self.assertTrue(set(move_3) - set(move_1) <= MOVE_1_BLOCK_REGISTERS)
        self.assertEqual({register for register in move_1
                          if register in move_3 and move_1[register] != move_3[register]}, set())

    def test_move_1_block_sets_feedl_big_endian(self):
        positions = move_carrier.MOVE_1_FEEDL_VALUE_POSITIONS
        self.assertEqual(bytes(move_carrier.MOVE_1_BLOCK_CAPTURED[positions.start - 1:positions.stop:2]),
                         bytes([0x3D, 0x3E, 0x3F]))
        self.assertEqual(move_carrier.move_1_block(97).sent,
                         bytes.fromhex(MOVE_1_BLOCK_10158.replace("3d00 3e27 3fae", "3d00 3e00 3f61")))
        self.assertEqual(move_carrier.move_1_block(97).frame, 6259)
        for steps in (0, 1001, 10158):
            with self.subTest(steps=steps):
                with self.assertRaises(PermissionError):
                    move_carrier.move_1_block(steps)

    def test_move_1_run_sends_the_listed_requests_and_exits_zero(self):
        scanner = FakeScanner(WORKING_UNIT_MOVE_1_REGISTERS)
        exit_code, records = run_move(scanner, as_move_1=True)
        self.assertEqual(exit_code, move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_move_1_transfers())
        self.assertEqual([record["frame"] for record in records_of_kind(records, "bulk_write")], [6267, 6275])
        self.assertEqual(records_of_kind(records, "register_read")[-1]["frame"], 6327)
        self.assertNotIn(write_transfer("0330"), scanner.transfers)
        self.assertEqual(scanner.transfers.count(write_transfer("0300")), 1)

    def test_move_1_steps_set_feedl(self):
        scanner = FakeScanner(WORKING_UNIT_MOVE_1_REGISTERS)
        self.assertEqual(run_move(scanner, steps=1000, as_move_1=True)[0], move_carrier.EXIT_GOOD)
        self.assertEqual(scanner.transfers, run_move_1_transfers(feedl_hex="0003e8"))

    def test_move_1_timeout_cuts_then_ends_with_motor_power_and_lamp_off(self):
        scanner = FakeScanner({**WORKING_UNIT_MOVE_1_REGISTERS, 0x101: [0xDC] + [0xDD] * 8 + [0xF5, 0xF4]})
        exit_code, records = run_move(scanner, poll_limit_seconds=0.1, as_move_1=True)
        self.assertEqual(exit_code, move_carrier.EXIT_MOTOR_TIMEOUT)
        self.assertEqual(scanner.transfers, run_move_1_transfers(polls=8, polls_after_cut=2))
        move_end = records_of_kind(records, "move_end")[0]
        self.assertEqual((move_end["cut_sent"], move_end["motorenb_cleared_after_cut"]), (True, True))

    def test_move_1_gate_refusal_sends_no_write(self):
        scanner = FakeScanner({**WORKING_UNIT_MOVE_1_REGISTERS, 0x101: 0x4C})
        self.assertEqual(run_move(scanner, as_move_1=True)[0], move_carrier.EXIT_OPEN_NOT_SENT)
        self.assertEqual(scanner.transfers, LOGGED_READ_TRANSFERS)

    def test_every_request_of_a_move_1_run_is_logged_and_checked(self):
        scanner = FakeScanner(WORKING_UNIT_MOVE_1_REGISTERS)
        with unittest.mock.patch.object(move_carrier, "check_allowed", wraps=move_carrier.check_allowed) as check, \
                unittest.mock.patch.object(vendor_open, "read_register", wraps=vendor_open.read_register) as read:
            _, records = run_move(scanner, as_move_1=True)
        self.assertEqual(check.call_count + read.call_count, len(scanner.transfers))
        request_kinds = {"register_state_write", "register_write", "register_read", "buffer_header", "bulk_write",
                         "upload_status_read", "link_check", "poll"}
        logged = len([record for record in records if record["kind"] in request_kinds])
        summaries = len(records_of_kind(records, "registers_before") + records_of_kind(records, "registers_after"))
        self.assertEqual(logged + summaries * len(LOGGED_READ_TRANSFERS), len(scanner.transfers))

    def test_move_1_table_hash_mismatch_sends_nothing_and_exits_24(self):
        uploads = list(move_carrier.TABLE_UPLOADS_MOVE_1)
        header, upload, status = uploads[1]
        uploads[1] = (header, dataclasses.replace(upload, sent=move_carrier.SLOPE_TABLE), status)
        scanner = FakeScanner(WORKING_UNIT_MOVE_1_REGISTERS)
        with unittest.mock.patch.object(move_carrier, "TABLE_UPLOADS_MOVE_1", tuple(uploads)):
            exit_code, records = run_move(scanner, as_move_1=True)
        self.assertEqual(exit_code, move_carrier.EXIT_TABLE_HASH)
        self.assertEqual(scanner.transfers, [])
        self.assertIn(move_carrier.SLOPE_TABLE_MOVE_1_SHA256, records_of_kind(records, "refused")[0]["reason"])

    def test_move_3_requests_are_refused_in_a_move_1_run_and_the_other_way_round(self):
        move_1_plan = move_carrier.MovePlan(97, True, lamp=True, as_move_1=True, register_33_read=0x1C)
        for request in (move_carrier.BEFORE_WRITE_0X02, move_carrier.BEFORE_WRITE_0X0A, move_carrier.feed_block(97),
                        move_carrier.TABLE_UPLOADS[0][1], move_carrier.register_33_write(6459, 0x3C),
                        move_carrier.BACKSCAN_SET, move_carrier.BACKSCAN_CLEAR, move_carrier.LAMP_AS_CAPTURED,
                        move_carrier.REGISTER_STATE_WRITES[0], move_carrier.move_1_block(98)):
            with self.subTest(variant="move 1", request=request.kind, sent=request.sent[:6].hex()):
                assert_refused(self, request, move_1_plan)
        for request in (move_carrier.move_1_block(97), move_carrier.TABLE_UPLOADS_MOVE_1[0][1],
                        move_carrier.REGISTER_STATE_MOVE_1_WRITES[0]):
            with self.subTest(variant="move 3", request=request.kind, sent=request.sent[:6].hex()):
                assert_refused(self, request, move_carrier.MovePlan(97, False))

    def test_backscan_and_lamp_as_captured_are_refused_with_as_move_1(self):
        self.assertTrue(move_carrier.parse_arguments(["logs", "--as-move-1"]).as_move_1)
        self.assertFalse(move_carrier.parse_arguments(["logs"]).as_move_1)
        for flag in ("--backscan", "--lamp-as-captured"):
            with self.subTest(flag=flag):
                with contextlib.redirect_stderr(io.StringIO()) as error_output:
                    with self.assertRaises(SystemExit) as raised:
                        move_carrier.parse_arguments(["logs", "--as-move-1", flag])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(flag, error_output.getvalue())
                move_carrier.parse_arguments(["logs", flag])


if __name__ == "__main__":
    unittest.main()
