"""Take a read-only snapshot of the OpticFilm 120's state, or compare two snapshots.

Sends only IN requests: the list of doc/protocol/playbook.md, "Status and
flags", part 3 ("A snapshot from the engine's own reads"), in its order.
Each request is one the issue #151 capture sends, or a register read of
Plustek's macOS engine in the capture's framing (the engine reads
registers with bRequest 0xa0, the capture with 0x04). Work item:
doc/work/0013-debugging-facilities.md, where snapshots
bracket the resets: snapshot, reset or experiment, snapshot again, diff
(playbook, "Resets", part 2).

What it reads, in this order (the step numbers are the playbook's):
1. c0 0c 008e wIndex 0x20, 1 byte, the Windows engine's write
   acknowledge. First, because the byte reports the last write once and
   then reads 0xaa (an inference in the playbook), so any read before it
   would hide what the last tool left behind.
2. One read of interrupt endpoint 0x83, 1 byte, 200 ms timeout, as the
   capture's moves 1 and 2 read it. A timeout is logged as "nothing".
   Second, because the read may consume a latched event (inference), so
   it comes before anything else that could change the event.
3. c0 0c 008a wIndex 0x26fe, 1 byte, the read of CIOUSB::InitInterrupt.
   Only the read: the write-back InitInterrupt sends when bit 0 is set is
   never sent.
4. c0 0c 008e wIndex 0x00, 1 byte, CIOUSB::IsHispeed.
5. c0 0c 008e wIndex 0x18, 1 byte, the busy poll after a bulk
   transaction.
6. Registers 0x101, 0x100, 0x102 to 0x105, 0x06 and 0x30 to 0x3c: the
   status registers, VALIDWORD, PWRBIT and the GPIO registers, read
   before the long sweep.
7. Registers 0x01 to 0x120, the range CScan::DumpAllRegFromAsic reads.
   Plustek's developers read it between calibration and scan steps, which
   suggests that the reads do not disturb the unit (an inference in the
   playbook).
8. Register 0x00, where CIOUSB::DumpAllRegistersToConsole starts. SANE
   reads the chip version from it when CHKVER (0x100 bit 4) is set.
9. Registers 0x101 and 0x100 again: a change since step 6 shows activity
   in the unit during the snapshot.
10. Only with --event-read: c0 0c 008e wIndex 0x21, 1 byte, the macOS
    engine's event read for this product. Off by default: the capture
    never sends it, the owner's unit has never been sent it, and it may
    clear a latched event like step 2 (inference).

Register reads use the capture's framing: c0 04 008e (018e from 0x100
up), wIndex (register & 0xff) << 8 | 0x22, wLength 2, answer the value
then 0x55 (doc/protocol/usb-requests.md, "Registers"). Every register
read must return 0x55 as its second byte. Otherwise the run stops with
exit 13 after logging the answer. No transfer is retried, and the
requests go back to back with no pause.

Safety: ALLOWED_VENDOR_READS holds exactly the control requests above,
and every control request is checked against it before it is sent. A
read of a register outside 0x00 to 0x120 is refused before that check.
Every control request goes through flash_dump.control_in, which sends
bmRequestType 0xc0 only. The interrupt read reads endpoint 0x83 only. The
tool has no OUT transfer, no bulk transfer and no write path:
test_snapshot.py checks that its source calls neither ctrl_transfer nor
write and that a run sends nothing but the list.

Every run writes LOG_DIRECTORY/<UTC stamp>/log.jsonl: one line per
request (kind, step, setup fields, bytes received), then, after the last
read, a "snapshot" record. Its "registers" map takes every register read
("0x00" to "0x120") to its value in hex, its "bytes" map takes the
one-byte answers (write_acknowledge, interrupt_endpoint, init_interrupt,
is_hispeed, bulk_busy, and event with --event-read) to their value in hex
or "nothing". A register read more than once (steps 6, 7 and 9) has one
value when all its reads agree, otherwise the values of all its reads in
order, separated by spaces. A run that stops early writes no snapshot
record.

Diff mode: snapshot.py --diff A/log.jsonl B/log.jsonl takes the snapshot
record of each file and prints one line per register or byte whose value
differs, "register 0x101: 4c -> dc" or "byte write_acknowledge: aa -> 55"
("absent" for a byte that only one snapshot has), registers first in
ascending order, then the bytes, and nothing else. It sends nothing and
needs no root, but imports pyusb like the other tools. It exits 0 whether
or not anything differs, and 2 (argparse) when a file cannot be read or
has no snapshot record.

Before a run: ~/plustek-preservation/probe-disabled exists next to this
script, so that watch-scanner.sh does not start the probe on the wake,
and no other scanner tool runs. Start the run after the watcher has
logged "probe disabled" for the connection. The tool refuses to start
while the file is missing or a probe_readonly.py, keep_awake.py,
vendor_open.py, flash_dump.py, eeprom_read.py, move_carrier.py or other
snapshot.py process runs (move_carrier.refusal_exit_code, which excludes
the tool's own process chain). The check works in both directions: the
other tools refuse to start while a snapshot runs, since the snapshot
holds the claim on interface 0 from the interrupt read until it exits.

Exit codes (1 and 2 are left to Python and argparse): 0 the snapshot is
complete, 10 scanner not found, 13 USB error (other than the timeout of
the interrupt read), short answer, register read without 0x55 as its
second byte, or refused request (the log names the step and the read), 16
probe-disabled missing or another scanner tool running, 19 bcdDevice
other than 0x0702.

Usage (on the Pi):
    sudo ~/plustek-preservation/venv/bin/python snapshot.py LOG_DIRECTORY [--event-read]
    ~/plustek-preservation/venv/bin/python snapshot.py --diff A/log.jsonl B/log.jsonl
"""

import argparse
import dataclasses
import json
import os
import pathlib
import sys
import typing

import usb.core

import move_carrier
from flash_dump import (EXIT_NOT_FOUND, EXIT_PROBE_ACTIVE, EXIT_USB_ERROR, Session, ShortTransferError, control_in,
                        find_scanner, log, new_run_directory, request_code_for)
from keep_awake import EXIT_WRONG_CHIP, GL128_BCD_DEVICE, LinkByteError
from vendor_open import EXIT_GOOD, require_link_byte

INTERRUPT_ENDPOINT = 0x83
INTERRUPT_LENGTH = 1
INTERRUPT_TIMEOUT_MILLISECONDS = 200
NO_INTERRUPT_ANSWER = "nothing"
REGISTER_READ_LOW_VALUE = 0x008E
REGISTER_READ_HIGH_VALUE = 0x018E
REGISTER_READ_INDEX_LOW_BYTE = 0x22
REGISTER_READ_LENGTH = 2
FLAG_REGISTERS = (0x101, 0x100, 0x102, 0x103, 0x104, 0x105, 0x06, *range(0x30, 0x3D))
DUMP_REGISTERS = tuple(range(0x01, 0x121))
FIRST_REGISTER = (0x00,)
STATUS_REGISTERS_AGAIN = (0x101, 0x100)
SNAPSHOT_REGISTERS = frozenset(range(0x00, 0x121))
ABSENT = "absent"


@dataclasses.dataclass(frozen=True)
class VendorRead:
    """A control IN request (bmRequestType 0xc0, sent by flash_dump.control_in): setup fields and answer length."""
    request: int
    value: int
    index: int
    length: int


@dataclasses.dataclass(frozen=True)
class ByteRead:
    """A one-byte read of the list, by its name in BYTE_READS and in the snapshot record."""
    step: int
    name: str


@dataclasses.dataclass(frozen=True)
class InterruptRead:
    """The one read of interrupt endpoint 0x83."""
    step: int
    name: str = "interrupt_endpoint"


@dataclasses.dataclass(frozen=True)
class RegisterRead:
    step: int
    register: int


@dataclasses.dataclass
class Answers:
    """What the reads returned so far: the one-byte answers by name, and (register, value) in read order."""
    one_byte_answers: dict = dataclasses.field(default_factory=dict)
    register_reads: list = dataclasses.field(default_factory=list)


def one_byte_read(value: int, index: int) -> VendorRead:
    return VendorRead(request_code_for(1), value, index, 1)


def register_request(register: int) -> VendorRead:
    """The register read framing: wValue 0x018e from 0x100 up, wIndex (register & 0xff) << 8 | 0x22."""
    value = REGISTER_READ_HIGH_VALUE if register & 0x100 else REGISTER_READ_LOW_VALUE
    index = (register & 0xFF) << 8 | REGISTER_READ_INDEX_LOW_BYTE
    return VendorRead(request_code_for(REGISTER_READ_LENGTH), value, index, REGISTER_READ_LENGTH)


BYTE_READS = {
    "write_acknowledge": one_byte_read(0x008E, 0x0020),
    "init_interrupt": one_byte_read(0x008A, 0x26FE),
    "is_hispeed": one_byte_read(0x008E, 0x0000),
    "bulk_busy": one_byte_read(0x008E, 0x0018),
    "event": one_byte_read(0x008E, 0x0021),
}
ALLOWED_VENDOR_READS = frozenset(BYTE_READS.values()) | {register_request(register) for register in SNAPSHOT_REGISTERS}

REQUEST_ERRORS = (usb.core.USBError, PermissionError, ShortTransferError, LinkByteError)


def register_reads(step: int, registers: tuple) -> tuple:
    return tuple(RegisterRead(step, register) for register in registers)


def snapshot_plan(event_read: bool) -> tuple:
    """The playbook's list in its order, step 10 only with event_read."""
    plan = (ByteRead(1, "write_acknowledge"), InterruptRead(2), ByteRead(3, "init_interrupt"),
            ByteRead(4, "is_hispeed"), ByteRead(5, "bulk_busy"), *register_reads(6, FLAG_REGISTERS),
            *register_reads(7, DUMP_REGISTERS), *register_reads(8, FIRST_REGISTER),
            *register_reads(9, STATUS_REGISTERS_AGAIN))
    return plan + ((ByteRead(10, "event"),) if event_read else ())


def register_key(register: int) -> str:
    return f"0x{register:02x}"


def name_of(planned) -> str:
    return register_key(planned.register) if isinstance(planned, RegisterRead) else planned.name


def setup_fields(request: VendorRead) -> dict:
    return {"request_type": "c0", "request": f"{request.request:02x}", "value": f"{request.value:04x}",
            "index": f"{request.index:04x}", "length": request.length}


def send_vendor_read(session: Session, request: VendorRead) -> bytes:
    """The request through flash_dump.control_in (bmRequestType 0xc0), after the allow-list check."""
    if request not in ALLOWED_VENDOR_READS:
        raise PermissionError(f"refusing wValue 0x{request.value:04x} wIndex 0x{request.index:04x} "
                              f"length {request.length}: not a read of the snapshot list")
    return control_in(session, request.request, request.value, request.index, request.length)


def read_byte(session: Session, planned: ByteRead) -> str:
    request = BYTE_READS[planned.name]
    received = send_vendor_read(session, request).hex()
    log(session, {"kind": "byte_read", "step": planned.step, "name": planned.name, **setup_fields(request),
                  "received": received})
    return received


def read_interrupt(session: Session, planned: InterruptRead) -> str:
    """One read of endpoint 0x83. A timeout or an empty answer is "nothing", any other USB error stops the run."""
    try:
        data = session.device.read(INTERRUPT_ENDPOINT, INTERRUPT_LENGTH, INTERRUPT_TIMEOUT_MILLISECONDS)
        received = bytes(data).hex(" ") or NO_INTERRUPT_ANSWER
    except usb.core.USBTimeoutError:
        received = NO_INTERRUPT_ANSWER
    log(session, {"kind": "interrupt_read", "step": planned.step, "name": planned.name,
                  "endpoint": f"{INTERRUPT_ENDPOINT:02x}", "length": INTERRUPT_LENGTH,
                  "timeout_milliseconds": INTERRUPT_TIMEOUT_MILLISECONDS, "received": received})
    return received


def read_register(session: Session, planned: RegisterRead) -> int:
    """A register of SNAPSHOT_REGISTERS: logged with both bytes received, then the 0x55 check."""
    if planned.register not in SNAPSHOT_REGISTERS:
        raise PermissionError(f"refusing read of register {register_key(planned.register)}")
    request = register_request(planned.register)
    received = send_vendor_read(session, request)
    log(session, {"kind": "register_read", "step": planned.step, "register": register_key(planned.register),
                  **setup_fields(request), "received": received.hex(" ")})
    require_link_byte(received[1], f"register {register_key(planned.register)}")
    return received[0]


def perform(session: Session, planned, answers: Answers) -> None:
    if isinstance(planned, RegisterRead):
        answers.register_reads.append((planned.register, read_register(session, planned)))
    elif isinstance(planned, InterruptRead):
        answers.one_byte_answers[planned.name] = read_interrupt(session, planned)
    else:
        answers.one_byte_answers[planned.name] = read_byte(session, planned)


def joined_values(values: list) -> str:
    """One value when all reads agree, otherwise every read in order."""
    shown = values if len(set(values)) > 1 else values[:1]
    return " ".join(f"{value:02x}" for value in shown)


def register_map(reads: list) -> dict:
    """Register (as 0x101) to its value, in ascending register order."""
    values_by_register = {}
    for register, value in reads:
        values_by_register.setdefault(register, []).append(value)
    return {register_key(register): joined_values(values_by_register[register])
            for register in sorted(values_by_register)}


def snapshot_record(answers: Answers) -> dict:
    return {"kind": "snapshot", "registers": register_map(answers.register_reads),
            "bytes": dict(answers.one_byte_answers)}


def take_snapshot(session: Session, plan: tuple) -> int:
    """Every read of the plan in order, then the snapshot record. Stops at the first error."""
    answers = Answers()
    for planned in plan:
        try:
            perform(session, planned, answers)
        except REQUEST_ERRORS as error:
            log(session, {"kind": "error", "step": planned.step, "read": name_of(planned), "error": str(error)})
            return EXIT_USB_ERROR
    log(session, snapshot_record(answers))
    return EXIT_GOOD


def run(session: Session, event_read: bool = False) -> int:
    exit_code = take_snapshot(session, snapshot_plan(event_read))
    log(session, {"kind": "exit", "code": exit_code})
    return exit_code


def read_log_records(path: pathlib.Path) -> list:
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def snapshot_from_log(path: pathlib.Path) -> dict:
    """The last snapshot record of a log.jsonl. ValueError when it has none (a run that stopped early)."""
    snapshots = [record for record in read_log_records(path) if record.get("kind") == "snapshot"]
    if not snapshots:
        raise ValueError(f"{path}: no snapshot record")
    return snapshots[-1]


def differing_entries(label: str, keys: list, first: dict, second: dict) -> list:
    return [f"{label} {key}: {first.get(key, ABSENT)} -> {second.get(key, ABSENT)}"
            for key in keys if first.get(key, ABSENT) != second.get(key, ABSENT)]


def snapshot_differences(first: dict, second: dict) -> list:
    """One line per register, then per byte, whose value differs between two snapshot records."""
    first_registers, second_registers = first["registers"], second["registers"]
    register_order = sorted(set(first_registers) | set(second_registers), key=lambda key: int(key, 16))
    first_bytes, second_bytes = first["bytes"], second["bytes"]
    byte_order = list(first_bytes) + [key for key in second_bytes if key not in first_bytes]
    return (differing_entries("register", register_order, first_registers, second_registers)
            + differing_entries("byte", byte_order, first_bytes, second_bytes))


def print_differences(parser: argparse.ArgumentParser, first_path: pathlib.Path, second_path: pathlib.Path) -> int:
    try:
        first, second = snapshot_from_log(first_path), snapshot_from_log(second_path)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for line in snapshot_differences(first, second):
        print(line)
    return EXIT_GOOD


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Take a read-only snapshot of the scanner's state, or compare two.")
    parser.add_argument("log_directory", type=pathlib.Path, nargs="?",
                        help="directory for the run's log.jsonl (snapshot mode)")
    parser.add_argument("--event-read", action="store_true",
                        help="also send step 10, the one-byte read at wIndex 0x21, which the capture never shows and "
                             "which may clear a latched event")
    parser.add_argument("--diff", type=pathlib.Path, nargs=2, metavar=("A_LOG", "B_LOG"),
                        help="print the registers and bytes that differ between the snapshot records of two log.jsonl "
                             "files, and send nothing")
    return parser


def option_conflict(arguments: argparse.Namespace) -> typing.Optional[str]:
    """Why the arguments cannot go together, or None."""
    if arguments.diff and arguments.log_directory is not None:
        return "--diff takes no LOG_DIRECTORY"
    if arguments.diff and arguments.event_read:
        return "--event-read is for a snapshot, not for --diff"
    if not arguments.diff and arguments.log_directory is None:
        return "LOG_DIRECTORY is required unless --diff is given"
    return None


def snapshot_of_scanner(log_directory: pathlib.Path, event_read: bool) -> int:
    probe_disabled = pathlib.Path(__file__).resolve().parent / "probe-disabled"
    device = find_scanner()
    refusal = move_carrier.refusal_exit_code(probe_disabled, pathlib.Path("/proc"), os.getpid(), device)
    if refusal is not None:
        messages = {EXIT_PROBE_ACTIVE: f"create {probe_disabled} and wait until no probe_readonly.py, keep_awake.py, "
                                       "vendor_open.py, flash_dump.py, eeprom_read.py, move_carrier.py or other "
                                       "snapshot.py process runs",
                    EXIT_NOT_FOUND: "scanner not found",
                    EXIT_WRONG_CHIP: f"bcdDevice is not 0x{GL128_BCD_DEVICE:04x}"}
        print(messages[refusal], file=sys.stderr)
        return refusal
    run_directory = new_run_directory(log_directory)
    print(f"output in {run_directory}", flush=True)
    with open(run_directory / "log.jsonl", "w") as log_file:
        session = Session(device, log_file)
        log(session, {"kind": "device", "vendor_id": f"{device.idVendor:04x}",
                      "product_id": f"{device.idProduct:04x}", "bcd_device": f"{device.bcdDevice:04x}",
                      "event_read": event_read})
        return run(session, event_read)


def main(argument_list: typing.Optional[list] = None) -> int:
    parser = argument_parser()
    arguments = parser.parse_args(argument_list)
    conflict = option_conflict(arguments)
    if conflict is not None:
        parser.error(conflict)
    if arguments.diff:
        return print_differences(parser, *arguments.diff)
    return snapshot_of_scanner(arguments.log_directory, arguments.event_read)


if __name__ == "__main__":
    sys.exit(main())
