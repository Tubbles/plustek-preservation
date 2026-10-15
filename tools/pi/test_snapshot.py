"""Tests for snapshot.py against a simulated scanner, no USB needed.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import ast
import contextlib
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

if not hasattr(usb.core, "USBTimeoutError"):  # pyusb has it as a subclass of USBError, the stub does not
    setattr(usb.core, "USBTimeoutError", type("USBTimeoutError", (usb.core.USBError,), {}))

import flash_dump
import move_carrier
import snapshot

TOOLS_DIRECTORY = pathlib.Path(__file__).resolve().parent
INTERRUPT_TRANSFER = ("interrupt", 0x83, 1, 200)
# The owner's unit after a wake (doc/protocol/playbook.md, "Resets", part 2). Other registers read as their low byte.
COLD_REGISTERS = {0x101: 0x4C, 0x06: 0x00, 0x31: 0xBC, 0x33: 0x1E, 0x34: 0x00, 0x36: 0x00}
COLD_ONE_BYTE_ANSWERS = {(0x008E, 0x0020): b"\xaa", (0x008A, 0x26FE): b"\x00", (0x008E, 0x0000): b"\x00",
                         (0x008E, 0x0018): b"\x02", (0x008E, 0x0021): b"\x00"}
STEP_6_REGISTERS = [0x101, 0x100, 0x102, 0x103, 0x104, 0x105, 0x06] + list(range(0x30, 0x3D))
STEP_7_REGISTERS = list(range(0x01, 0x121))
PLAYBOOK_REGISTERS = STEP_6_REGISTERS + STEP_7_REGISTERS + [0x00, 0x101, 0x100]


def register_transfer(register: int) -> tuple:
    return (0xC0, 0x04, 0x018E if register >= 0x100 else 0x008E, ((register & 0xFF) << 8) | 0x22, 2)


def byte_transfer(value: int, index: int) -> tuple:
    return (0xC0, 0x0C, value, index, 1)


EVENT_TRANSFER = byte_transfer(0x008E, 0x0021)
EXPECTED_TRANSFERS = ([byte_transfer(0x008E, 0x0020), INTERRUPT_TRANSFER, byte_transfer(0x008A, 0x26FE),
                       byte_transfer(0x008E, 0x0000), byte_transfer(0x008E, 0x0018)]
                      + [register_transfer(register) for register in PLAYBOOK_REGISTERS])
COLD_BYTES = {"write_acknowledge": "aa", "interrupt_endpoint": "nothing", "init_interrupt": "00", "is_hispeed": "00",
              "bulk_busy": "02"}


class FakeScanner:
    """Answers the snapshot's reads. An OUT request, a buffer on an IN request or an unknown read fails the test.

    It has no write method, so a bulk or interrupt OUT transfer fails the
    test too. register_values maps a register to a value or to a list of
    values returned in turn (the last one repeats). Registers not in it
    read as their low byte. interrupt_answer None makes the interrupt read
    time out. fail_on is a predicate on the transfer tuple that makes that
    transfer raise a USB error. bad_register_read_number makes that
    register read answer 0x00 as its second byte, short_answer_number makes
    that transfer answer one byte short.
    """

    def __init__(self, register_values=None, one_byte_answers=None, interrupt_answer=None, bcd_device=0x0702,
                 fail_on=None, bad_register_read_number=None, short_answer_number=None):
        values = register_values if register_values is not None else COLD_REGISTERS
        self.register_values = {register: list(value) if isinstance(value, list) else value
                                for register, value in values.items()}
        self.one_byte_answers = one_byte_answers if one_byte_answers is not None else COLD_ONE_BYTE_ANSWERS
        self.interrupt_answer = interrupt_answer
        self.bcdDevice = bcd_device
        self.idVendor, self.idProduct, self.bus, self.address = 0x07B3, 0x1406, 1, 5
        self.fail_on = fail_on
        self.bad_register_read_number = bad_register_read_number
        self.short_answer_number = short_answer_number
        self.transfers = []
        self.register_reads = 0

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        self.transfers.append((request_type, request, value, index, data_or_length))
        if request_type != 0xC0:
            raise AssertionError(f"bmRequestType 0x{request_type:02x}")
        if not isinstance(data_or_length, int):
            raise AssertionError("IN request with a data buffer")
        if request != flash_dump.request_code_for(data_or_length):
            raise AssertionError(f"bRequest 0x{request:02x} for {data_or_length} bytes")
        if self.fail_on is not None and self.fail_on(self.transfers[-1]):
            raise usb.core.USBError("Pipe error")
        answer = self.answer(value, index, data_or_length)
        return answer[:-1] if len(self.transfers) == self.short_answer_number else answer

    def answer(self, value, index, length):
        if value in (0x008E, 0x018E) and index & 0xFF == 0x22 and length == 2:
            self.register_reads += 1
            link = 0x00 if self.register_reads == self.bad_register_read_number else 0x55
            return bytes([self.next_register_value((index >> 8) | (value & 0x100)), link])
        if length != 1 or (value, index) not in self.one_byte_answers:
            raise AssertionError(f"IN wValue 0x{value:04x} wIndex 0x{index:04x} length {length}")
        return self.one_byte_answers[(value, index)]

    def next_register_value(self, register):
        value = self.register_values.get(register, register & 0xFF)
        if not isinstance(value, list):
            return value
        return value.pop(0) if len(value) > 1 else value[0]

    def read(self, endpoint, size, timeout):
        self.transfers.append(("interrupt", endpoint, size, timeout))
        if endpoint != 0x83:
            raise AssertionError(f"read of endpoint 0x{endpoint:02x}")
        if self.fail_on is not None and self.fail_on(self.transfers[-1]):
            raise usb.core.USBError("Resource busy")
        if self.interrupt_answer is None:
            raise usb.core.USBTimeoutError("Operation timed out")
        return self.interrupt_answer


def run_snapshot(scanner, event_read=False):
    """Run run() and return the exit code and the log records."""
    log_file = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()):
        exit_code = snapshot.run(flash_dump.Session(scanner, log_file), event_read)
    return exit_code, [json.loads(line) for line in log_file.getvalue().splitlines()]


def records_of_kind(records, kind):
    return [record for record in records if record["kind"] == kind]


def request_records(records):
    return [record for record in records if record["kind"] in ("byte_read", "interrupt_read", "register_read")]


def snapshot_of(records):
    return records_of_kind(records, "snapshot")[0]


def snapshot_names():
    return [snapshot.register_key(register) for register in range(0x121)]


class RequestOrderTests(unittest.TestCase):
    def test_default_run_sends_the_playbook_list_in_order(self):
        scanner = FakeScanner()
        exit_code, records = run_snapshot(scanner)
        self.assertEqual(exit_code, snapshot.EXIT_GOOD)
        self.assertEqual(scanner.transfers, EXPECTED_TRANSFERS)
        self.assertEqual(len(scanner.transfers), 316)
        self.assertEqual([record["kind"] for record in records[-2:]], ["snapshot", "exit"])

    def test_event_read_adds_the_0x21_read_last(self):
        scanner = FakeScanner()
        exit_code, records = run_snapshot(scanner, event_read=True)
        self.assertEqual(exit_code, snapshot.EXIT_GOOD)
        self.assertEqual(scanner.transfers, EXPECTED_TRANSFERS + [EVENT_TRANSFER])
        self.assertEqual(request_records(records)[-1]["step"], 10)

    def test_register_framing_matches_the_capture(self):
        self.assertEqual(snapshot.register_request(0x101), snapshot.VendorRead(0x04, 0x018E, 0x0122, 2))  # frame 73
        self.assertEqual(snapshot.register_request(0x36), snapshot.VendorRead(0x04, 0x008E, 0x3622, 2))  # frame 113
        self.assertEqual(snapshot.register_request(0x120), snapshot.VendorRead(0x04, 0x018E, 0x2022, 2))
        self.assertEqual(snapshot.register_request(0x00), snapshot.VendorRead(0x04, 0x008E, 0x0022, 2))

    def test_every_request_is_logged_once_with_its_step(self):
        _, records = run_snapshot(FakeScanner())
        logged = request_records(records)
        self.assertEqual([record["step"] for record in logged],
                         [1, 2, 3, 4, 5] + [6] * 20 + [7] * 288 + [8] + [9, 9])
        registers = [record for record in logged if record["kind"] == "register_read"]
        self.assertEqual([record["register"] for record in registers],
                         [snapshot.register_key(register) for register in PLAYBOOK_REGISTERS])
        self.assertEqual((registers[0]["register"], registers[0]["value"], registers[0]["index"],
                          registers[0]["received"]), ("0x101", "018e", "0122", "4c 55"))
        self.assertEqual(logged[0], {**logged[0], "name": "write_acknowledge", "request": "0c", "value": "008e",
                                     "index": "0020", "received": "aa"})


class SnapshotRecordTests(unittest.TestCase):
    def test_snapshot_holds_every_register_and_byte(self):
        _, records = run_snapshot(FakeScanner())
        record = snapshot_of(records)
        self.assertEqual(list(record["registers"]), snapshot_names())
        self.assertEqual({key: record["registers"][key] for key in ("0x00", "0x06", "0x31", "0x8e", "0x101", "0x120")},
                         {"0x00": "00", "0x06": "00", "0x31": "bc", "0x8e": "8e", "0x101": "4c", "0x120": "20"})
        self.assertEqual(record["bytes"], COLD_BYTES)

    def test_a_register_that_changes_during_the_snapshot_keeps_every_read(self):
        scanner = FakeScanner({**COLD_REGISTERS, 0x101: [0x4C, 0x4C, 0xDC], 0x34: [0x00, 0x80]})
        _, records = run_snapshot(scanner)
        registers = snapshot_of(records)["registers"]
        self.assertEqual((registers["0x101"], registers["0x34"], registers["0x100"]), ("4c 4c dc", "00 80", "00"))

    def test_event_read_adds_the_event_byte(self):
        _, records = run_snapshot(FakeScanner(), event_read=True)
        self.assertEqual(snapshot_of(records)["bytes"], {**COLD_BYTES, "event": "00"})


class InterruptTests(unittest.TestCase):
    def test_timeout_is_logged_as_nothing_and_the_run_goes_on(self):
        exit_code, records = run_snapshot(FakeScanner(interrupt_answer=None))
        self.assertEqual(exit_code, snapshot.EXIT_GOOD)
        interrupt = records_of_kind(records, "interrupt_read")[0]
        self.assertEqual((interrupt["step"], interrupt["endpoint"], interrupt["length"],
                          interrupt["timeout_milliseconds"], interrupt["received"]), (2, "83", 1, 200, "nothing"))

    def test_an_answer_is_logged_in_hex(self):
        _, records = run_snapshot(FakeScanner(interrupt_answer=bytes([0x40])))
        self.assertEqual(records_of_kind(records, "interrupt_read")[0]["received"], "40")
        self.assertEqual(snapshot_of(records)["bytes"]["interrupt_endpoint"], "40")

    def test_other_usb_error_stops_the_run_at_step_2(self):
        scanner = FakeScanner(fail_on=lambda transfer: transfer == INTERRUPT_TRANSFER)
        exit_code, records = run_snapshot(scanner)
        self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
        error = records_of_kind(records, "error")[0]
        self.assertEqual((error["step"], error["read"]), (2, "interrupt_endpoint"))
        self.assertEqual(scanner.transfers, EXPECTED_TRANSFERS[:2])
        self.assertEqual(records_of_kind(records, "snapshot"), [])


class ErrorTests(unittest.TestCase):
    def assert_stopped_at(self, scanner, step, read_name, transfer_count):
        exit_code, records = run_snapshot(scanner)
        self.assertEqual(exit_code, flash_dump.EXIT_USB_ERROR)
        error = records_of_kind(records, "error")[0]
        self.assertEqual((error["step"], error["read"]), (step, read_name))
        self.assertEqual(scanner.transfers, EXPECTED_TRANSFERS[:transfer_count])
        self.assertEqual(records_of_kind(records, "snapshot"), [])
        self.assertEqual(records[-1], {**records[-1], "kind": "exit", "code": 13})
        return records

    def test_register_read_without_0x55_is_logged_then_stops_the_run(self):
        records = self.assert_stopped_at(FakeScanner(bad_register_read_number=21), 7, "0x01", 5 + 21)
        self.assertEqual(records_of_kind(records, "register_read")[-1]["received"], "01 00")

    def test_short_answer_stops_the_run(self):
        self.assert_stopped_at(FakeScanner(short_answer_number=4), 4, "is_hispeed", 4)

    def test_usb_error_in_the_sweep_stops_the_run(self):
        failing = register_transfer(0x8B)
        scanner = FakeScanner(fail_on=lambda transfer: transfer == failing)
        self.assert_stopped_at(scanner, 7, "0x8b", EXPECTED_TRANSFERS.index(failing) + 1)


class SafetyTests(unittest.TestCase):
    def session(self, scanner):
        return flash_dump.Session(scanner, io.StringIO())

    def test_allow_list_is_exactly_the_playbook_requests(self):
        expected = ({transfer[1:] for transfer in EXPECTED_TRANSFERS + [EVENT_TRANSFER] if transfer[0] == 0xC0}
                    | {register_transfer(register)[1:] for register in range(0x121)})
        allowed = {(read.request, read.value, read.index, read.length) for read in snapshot.ALLOWED_VENDOR_READS}
        self.assertEqual(allowed, expected)
        self.assertEqual(len(allowed), 5 + 0x121)

    def test_runs_send_nothing_but_control_in_requests_and_the_interrupt_read(self):
        self.assertFalse(hasattr(FakeScanner(), "write"))
        scanners = (FakeScanner(), FakeScanner(interrupt_answer=b"\x04"), FakeScanner(bad_register_read_number=3))
        for event_read in (False, True):
            for scanner in scanners:
                with self.subTest(event_read=event_read, scanner=scanner):
                    run_snapshot(scanner, event_read)
                    control = [transfer for transfer in scanner.transfers if transfer != INTERRUPT_TRANSFER]
                    self.assertEqual(scanner.transfers.count(INTERRUPT_TRANSFER), 1)
                    self.assertEqual({transfer[0] for transfer in control}, {0xC0})
                    scanner.transfers.clear()
                    scanner.register_reads = 0

    def test_source_has_no_out_request_and_no_write(self):
        tree = ast.parse((TOOLS_DIRECTORY / "snapshot.py").read_text())
        calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
        called_attributes = {called.attr for called in calls if isinstance(called, ast.Attribute)}
        self.assertFalse(called_attributes & {"ctrl_transfer", "write"})
        device_calls = {called.attr for called in calls if isinstance(called, ast.Attribute)
                        and isinstance(called.value, ast.Attribute) and called.value.attr == "device"}
        self.assertEqual(device_calls, {"read"})
        integers = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and type(node.value) is int}
        self.assertNotIn(0x40, integers)

    def test_only_reviewed_names_come_from_the_other_tools(self):
        # None of these sends an OUT request. A new name taken from another tool has to be checked and added here.
        tools = {"flash_dump", "keep_awake", "move_carrier", "vendor_open", "eeprom_read", "probe_readonly"}
        tree = ast.parse((TOOLS_DIRECTORY / "snapshot.py").read_text())
        taken = {(node.module, alias.name) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                 and node.module in tools for alias in node.names}
        taken |= {(node.value.id, node.attr) for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                  and isinstance(node.value, ast.Name) and node.value.id in tools}
        self.assertEqual(taken, {
            ("flash_dump", "EXIT_NOT_FOUND"), ("flash_dump", "EXIT_PROBE_ACTIVE"), ("flash_dump", "EXIT_USB_ERROR"),
            ("flash_dump", "Session"), ("flash_dump", "ShortTransferError"), ("flash_dump", "control_in"),
            ("flash_dump", "find_scanner"), ("flash_dump", "log"), ("flash_dump", "new_run_directory"),
            ("flash_dump", "request_code_for"), ("keep_awake", "EXIT_WRONG_CHIP"),
            ("keep_awake", "GL128_BCD_DEVICE"), ("keep_awake", "LinkByteError"), ("vendor_open", "EXIT_GOOD"),
            ("vendor_open", "require_link_byte"), ("move_carrier", "refusal_exit_code")})

    def test_control_in_sends_bm_request_type_0xc0_only(self):
        tree = ast.parse((TOOLS_DIRECTORY / "flash_dump.py").read_text())
        control_in = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.FunctionDef) and node.name == "control_in")
        transfers = [node for node in ast.walk(control_in) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "ctrl_transfer"]
        self.assertEqual(len(transfers), 1)
        self.assertEqual(ast.literal_eval(transfers[0].args[0]), 0xC0)

    def test_register_outside_the_list_is_refused(self):
        # 0x200 and 0x220 would frame as 0x00 and 0x20, so the register itself is checked before the framing.
        scanner = FakeScanner()
        for register in (0x121, 0x1FF, 0x200, 0x220, -1):
            with self.subTest(register=register):
                with self.assertRaisesRegex(PermissionError, "refusing read of register"):
                    snapshot.read_register(self.session(scanner), snapshot.RegisterRead(7, register))
        self.assertEqual(scanner.transfers, [])

    def test_vendor_read_outside_the_list_is_refused(self):
        scanner = FakeScanner()
        refused = (snapshot.VendorRead(0x04, 0x008A, 0x0010, 3),  # flash ID
                   snapshot.VendorRead(0x04, 0x008A, 0x0005, 4),  # APB data
                   snapshot.VendorRead(0x04, 0x008A, 0x310A, 2),  # the second register read encoding
                   snapshot.VendorRead(0x04, 0x008E, 0x0020, 2),  # write acknowledge, wrong length
                   snapshot.VendorRead(0x04, 0x008E, 0x3122, 3),  # ReadReg(reg, ushort*)
                   snapshot.VendorRead(0xA0, 0x008E, 0x3122, 2))  # the macOS engine's bRequest
        for request in refused:
            with self.subTest(request=request):
                with self.assertRaisesRegex(PermissionError, "not a read of the snapshot list"):
                    snapshot.send_vendor_read(self.session(scanner), request)
        self.assertEqual(scanner.transfers, [])


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
        tool = b"/home/pi/plustek-preservation/snapshot.py"
        self.add_process(297, [b"bash", b"-c", b"sudo venv/bin/python " + tool + b" scanner-log/snapshot"], parent=1)
        self.add_process(298, [b"sudo", b"venv/bin/python", tool, b"scanner-log/snapshot"], parent=297)
        self.add_process(299, [b"sudo", b"venv/bin/python", tool, b"scanner-log/snapshot"], parent=298)
        self.add_process(self.OWN_PID, [b"venv/bin/python", tool, b"scanner-log/snapshot"], parent=299)

    def add_process(self, pid, arguments, parent=1):
        (self.proc_root / str(pid)).mkdir()
        (self.proc_root / str(pid) / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")
        (self.proc_root / str(pid) / "stat").write_text(f"{pid} (some (name)) S {parent} {pid} {pid} 0 -1\n")

    def remove_process(self, pid):
        for name in ("cmdline", "stat"):
            (self.proc_root / str(pid) / name).unlink()
        (self.proc_root / str(pid)).rmdir()

    def refusal(self, device):
        # The check snapshot_of_scanner runs: move_carrier's, whose tool list has snapshot.py (reviewed 2026-10-15).
        return move_carrier.refusal_exit_code(self.probe_disabled, self.proc_root, self.OWN_PID, device)

    def test_good_start_with_its_own_process_chain(self):
        self.add_process(100, [b"/bin/sh", b"./watch-scanner.sh"])
        self.assertIsNone(self.refusal(FakeScanner()))

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
                self.remove_process(pid)

    def test_no_scanner_is_exit_10(self):
        self.assertEqual(self.refusal(None), flash_dump.EXIT_NOT_FOUND)

    def test_other_bcd_device_is_exit_19(self):
        self.assertEqual(self.refusal(FakeScanner(bcd_device=0x0701)), snapshot.EXIT_WRONG_CHIP)


class DiffTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = pathlib.Path(directory.name)

    def write_log(self, name, scanner, event_read=False):
        _, records = run_snapshot(scanner, event_read)
        path = self.directory / name
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        return path

    def run_main(self, argument_list):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = snapshot.main(argument_list)
        return exit_code, output.getvalue().splitlines()

    def test_differences_list_registers_in_numeric_order_then_bytes(self):
        first = {"registers": {"0x06": "00", "0x31": "bc", "0x101": "4c", "0x120": "20"},
                 "bytes": {"write_acknowledge": "aa", "interrupt_endpoint": "nothing"}}
        second = {"registers": {"0x06": "18", "0x31": "be", "0x101": "dc", "0x120": "20"},
                  "bytes": {"write_acknowledge": "55", "interrupt_endpoint": "nothing", "event": "00"}}
        self.assertEqual(snapshot.snapshot_differences(first, second),
                         ["register 0x06: 00 -> 18", "register 0x31: bc -> be", "register 0x101: 4c -> dc",
                          "byte write_acknowledge: aa -> 55", "byte event: absent -> 00"])
        self.assertEqual(snapshot.snapshot_differences(first, first), [])

    def test_diff_mode_prints_only_the_differences(self):
        cold = self.write_log("cold.jsonl", FakeScanner())
        opened = self.write_log("opened.jsonl", FakeScanner(
            {**COLD_REGISTERS, 0x101: 0xDC, 0x06: 0x18, 0x34: [0x80, 0x81]},
            {**COLD_ONE_BYTE_ANSWERS, (0x008E, 0x0020): b"\x55"}), event_read=True)
        exit_code, lines = self.run_main(["--diff", str(cold), str(opened)])
        self.assertEqual(exit_code, snapshot.EXIT_GOOD)
        self.assertEqual(lines, ["register 0x06: 00 -> 18", "register 0x34: 00 -> 80 81",
                                 "register 0x101: 4c -> dc", "byte write_acknowledge: aa -> 55",
                                 "byte event: absent -> 00"])
        self.assertEqual(self.run_main(["--diff", str(cold), str(cold)]), (snapshot.EXIT_GOOD, []))

    def test_a_log_without_a_snapshot_record_or_a_missing_file_is_exit_2(self):
        stopped = self.write_log("stopped.jsonl", FakeScanner(bad_register_read_number=1))
        cold = self.write_log("cold.jsonl", FakeScanner())
        for first, second, message in ((cold, stopped, "no snapshot record"),
                                       (self.directory / "missing.jsonl", cold, "No such file")):
            with self.subTest(message=message):
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as stop:
                    self.run_main(["--diff", str(first), str(second)])
                self.assertEqual(stop.exception.code, 2)
                self.assertIn(message, errors.getvalue())


class ArgumentTests(unittest.TestCase):
    def test_snapshot_and_diff_modes(self):
        parser = snapshot.argument_parser()
        plain = parser.parse_args(["logs"])
        self.assertEqual((plain.log_directory, plain.event_read, plain.diff), (pathlib.Path("logs"), False, None))
        self.assertTrue(parser.parse_args(["logs", "--event-read"]).event_read)
        compare = parser.parse_args(["--diff", "a/log.jsonl", "b/log.jsonl"])
        self.assertEqual((compare.log_directory, compare.diff),
                         (None, [pathlib.Path("a/log.jsonl"), pathlib.Path("b/log.jsonl")]))
        for arguments in (plain, compare):
            self.assertIsNone(snapshot.option_conflict(arguments))

    def test_conflicting_arguments_are_exit_2_before_any_usb_access(self):
        for argument_list in ([], ["logs", "--diff", "a", "b"], ["--diff", "a", "b", "--event-read"],
                              ["--diff", "a"]):
            with self.subTest(argument_list=argument_list):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                    snapshot.main(argument_list)
                self.assertEqual(stop.exception.code, 2)

    def test_exit_codes(self):
        self.assertEqual((snapshot.EXIT_GOOD, snapshot.EXIT_NOT_FOUND, snapshot.EXIT_USB_ERROR,
                          snapshot.EXIT_PROBE_ACTIVE, snapshot.EXIT_WRONG_CHIP), (0, 10, 13, 16, 19))


if __name__ == "__main__":
    unittest.main()
