#!/usr/bin/env python3
"""Turn decode.py JSON lines into a GL124/GL128 operation listing.

Usage: annotate_gl128.py [transfers.jsonl]   (reads stdin without a path)

Each USB request is paired with its completion (same IRP id), classified as a
GL124/GL128 operation and printed as one line:

    <first frame>-<last frame>  <seconds>  <operation>

Consecutive identical operations (status polling) are folded into one line
with a repeat count, consecutive bulk transfers on one endpoint into one
line with a byte total, and the one-byte link check (request 0x0c, wValue
0x8e, wIndex 0x20) that the vendor driver sends after most writes is shown
as a suffix of the operation it follows.

Request framing, from SANE backend/genesys:
  low.h:105-119                    request and value codes
  scanner_interface_usb.cpp:50-57  register read: 0xc0/0x04, wValue 0x8e
                                   (|0x100 above 0xff), wIndex 0x22+(addr<<8)
  scanner_interface_usb.cpp:97-106 register write: 0x40/0x04, wValue 0x83
                                   (|0x100 above 0xff), data (addr low, value)
  scanner_interface_usb.cpp:180-184 0x40/0x0c, wValue 0x8c, wIndex = index
  scanner_interface_usb.cpp:383-407 buffer header: 0x40/0x04, wValue 0x82,
                                   8 bytes (address LE32, size LE32)
"""

import dataclasses
import json
import sys
from typing import Iterable, Optional

REQUEST_TYPE_VENDOR_OUT = 0x40
REQUEST_TYPE_VENDOR_IN = 0xC0
REQUEST_BUFFER = 0x04
REQUEST_REGISTER = 0x0C
VALUE_BUFFER = 0x82
VALUE_SET_REGISTER = 0x83
VALUE_BUF_ENDACCESS = 0x8C
VALUE_GET_REGISTER = 0x8E
HIGH_ADDRESS_FLAG = 0x100
REGISTER_READ_INDEX_BASE = 0x22
LINK_OK = 0x55
LINK_CHECK_INDEX = 0x20

# Short register hints from SANE's GL124 register header and pyopticfilm's
# GL128 register reference (GL124 names on the GL128 are an analogy).
REGISTER_HINTS = {
    0x01: "scan control",          # gl124_registers.h:33-41
    0x02: "motor control",         # gl124_registers.h:43-51
    0x03: "lamp",                  # gl124_registers.h:53-58
    0x0D: "clear counters",        # gl124_registers.h:126-131
    0x0F: "start",                 # gl124_registers.h:133
    0x51: "AFE index",             # pyopticfilm docs/register-reference.md:35
    0x5D: "AFE data high",
    0x5E: "AFE data low",
    0x100: "status 0x100",         # gl124_registers.h:245-253
    0x101: "status",               # pyopticfilm docs/register-reference.md:40
}

BUFFER_HEADER_MODES = {0x00: "read", 0x01: "write", 0x08: "read wIndex 0x08"}

STANDARD_REQUEST_NAMES = {
    0x00: "GET_STATUS", 0x01: "CLEAR_FEATURE", 0x03: "SET_FEATURE",
    0x05: "SET_ADDRESS", 0x06: "GET_DESCRIPTOR", 0x08: "GET_CONFIGURATION",
    0x09: "SET_CONFIGURATION", 0x0A: "GET_INTERFACE", 0x0B: "SET_INTERFACE",
}

DESCRIPTOR_TYPE_NAMES = {1: "device", 2: "configuration", 3: "string"}


@dataclasses.dataclass
class Transaction:
    """A submitted request and its completion (either may be missing).

    data_stage is the separate data-stage record that USBPcap versions before
    1.5.0.0 write for a control transfer with data.
    """

    submit: Optional[dict]
    complete: Optional[dict]
    data_stage: Optional[dict] = None


@dataclasses.dataclass
class Operation:
    """One line of the listing."""

    first_frame: int
    last_frame: int
    time: Optional[float]
    kind: str
    text: str
    endpoint: int = 0
    byte_total: int = 0
    count: int = 1


# --- pairing ----------------------------------------------------------------


def is_control_data_stage(record: dict) -> bool:
    return record.get("control_stage") == "data"


def pair_transactions(records: Iterable[dict]) -> list[Transaction]:
    """Pair submit and completion records by IRP id, in submit order.

    USBPcap before 1.5.0.0 writes a control transfer as setup, optional data
    and status records under one IRP id. Since 1.5.0.0 the OUT data sits in
    the setup record and the IN data in the completion
    (https://desowin.org/usbpcap/captureformat.html). Both layouts end up in
    one transaction.
    """
    transactions: list[Transaction] = []
    pending: dict[str, Transaction] = {}
    for record in records:
        if is_control_data_stage(record) and record["irp_id"] in pending:
            pending[record["irp_id"]].data_stage = record
        elif record["event"] == "submit":
            transaction = Transaction(record, None)
            pending[record["irp_id"]] = transaction
            transactions.append(transaction)
        elif record["irp_id"] in pending:
            pending.pop(record["irp_id"]).complete = record
        else:
            transactions.append(Transaction(None, record))
    return transactions


def first_record(transaction: Transaction) -> dict:
    return transaction.submit or transaction.complete


def frame_range(transaction: Transaction) -> tuple[int, int]:
    first = first_record(transaction)["frame"]
    last = transaction.complete["frame"] if transaction.complete else first
    return first, last


def record_data(record: Optional[dict]) -> bytes:
    return b"" if record is None else bytes.fromhex(record["data_hex"])


def data_stage_is_in(transaction: Transaction) -> bool:
    """Direction of a separate data stage, from bit 7 of bmRequestType."""
    setup = transaction.submit.get("setup") if transaction.submit else None
    return setup is not None and setup["bmRequestType"] & 0x80 != 0


def completion_data(transaction: Transaction) -> bytes:
    if transaction.data_stage is not None and data_stage_is_in(transaction):
        return record_data(transaction.data_stage)
    return record_data(transaction.complete)


def submit_data(transaction: Transaction) -> bytes:
    if transaction.data_stage is not None and not data_stage_is_in(transaction):
        return record_data(transaction.data_stage)
    return record_data(transaction.submit)


def status_suffix(transaction: Transaction) -> str:
    """' status=0x...' for a failed completion, '' otherwise."""
    if transaction.complete is None:
        return " (no completion in capture)"
    status = transaction.complete["usbd_status"]
    return "" if status == 0 else " status=0x%08x" % status


# --- control transfers --------------------------------------------------------


def register_name(address: int) -> str:
    hint = REGISTER_HINTS.get(address)
    return "0x%02x" % address if hint is None else "0x%02x (%s)" % (address, hint)


def register_pairs(setup: dict, data: bytes) -> list[tuple[int, int]]:
    """(address, value) pairs of a register write payload."""
    high = HIGH_ADDRESS_FLAG if setup["wValue"] & HIGH_ADDRESS_FLAG else 0
    return [(high | data[index], data[index + 1])
            for index in range(0, len(data) - 1, 2)]


def describe_register_write(setup: dict, data: bytes) -> tuple[str, str]:
    pairs = register_pairs(setup, data)
    if len(pairs) == 1:
        address, value = pairs[0]
        return "write", "write %s = 0x%02x" % (register_name(address), value)
    listing = " ".join("0x%02x=0x%02x" % pair for pair in pairs)
    return "write", "write %d registers: %s" % (len(pairs), listing)


def read_address(setup: dict) -> int:
    high = HIGH_ADDRESS_FLAG if setup["wValue"] & HIGH_ADDRESS_FLAG else 0
    return high | (setup["wIndex"] >> 8)


def describe_register_read(setup: dict, data: bytes) -> tuple[str, str]:
    address = read_address(setup)
    if len(data) < 2:
        return "read", "read %s -> (no data)" % register_name(address)
    link = "" if data[1] == LINK_OK else " [link byte 0x%02x]" % data[1]
    return "read", "read %s -> 0x%02x%s" % (register_name(address), data[0], link)


def describe_request_read(setup: dict, data: bytes) -> tuple[str, str]:
    value = "0x%02x" % data[0] if data else "(no data)"
    return "request_read", "request read wIndex 0x%02x -> %s" % (setup["wIndex"], value)


def describe_0x8c(setup: dict, data: bytes) -> tuple[str, str]:
    value = "0x%02x" % data[0] if data else "(no data)"
    return "write_0x8c", "write_0x8c index 0x%02x = %s" % (setup["wIndex"], value)


def describe_buffer_header(setup: dict, data: bytes) -> tuple[str, str]:
    address = int.from_bytes(data[0:4], "little")
    size = int.from_bytes(data[4:8], "little")
    mode = BUFFER_HEADER_MODES.get(setup["wIndex"], "wIndex 0x%02x" % setup["wIndex"])
    return "buffer_header", "buffer %s: address 0x%08x size %d" % (mode, address, size)


def describe_standard(setup: dict, data: bytes) -> tuple[str, str]:
    name = STANDARD_REQUEST_NAMES.get(setup["bRequest"], "request 0x%02x" % setup["bRequest"])
    if setup["bRequest"] != 0x06:
        return "standard", "%s wValue 0x%04x wIndex 0x%04x" % (name, setup["wValue"], setup["wIndex"])
    descriptor_type = setup["wValue"] >> 8
    descriptor_index = setup["wValue"] & 0xFF
    type_name = DESCRIPTOR_TYPE_NAMES.get(descriptor_type, "type 0x%02x" % descriptor_type)
    text = "%s %s index %d -> %s" % (name, type_name, descriptor_index, data.hex())
    if descriptor_type == 3 and descriptor_index != 0 and len(data) > 2:
        text += " %r" % data[2:].decode("utf-16-le", errors="replace")
    return "standard", text


def describe_other_control(setup: dict, out_data: bytes, in_data: bytes) -> tuple[str, str]:
    direction = "IN" if setup["bmRequestType"] & 0x80 else "OUT"
    payload = in_data if direction == "IN" else out_data
    arrow = "->" if direction == "IN" else "data"
    return "other", "vendor %s bmRequestType 0x%02x bRequest 0x%02x wValue 0x%04x " \
        "wIndex 0x%04x wLength %d %s %s" % (
            direction, setup["bmRequestType"], setup["bRequest"], setup["wValue"],
            setup["wIndex"], setup["wLength"], arrow, payload.hex() or "(none)")


def classify_vendor_out(setup: dict, data: bytes) -> Optional[tuple[str, str]]:
    request, value = setup["bRequest"], setup["wValue"]
    if request == REQUEST_BUFFER and value & 0xFF == VALUE_SET_REGISTER and setup["wIndex"] == 0:
        return describe_register_write(setup, data)
    if request == REQUEST_BUFFER and value == VALUE_BUFFER and len(data) == 8:
        return describe_buffer_header(setup, data)
    if request == REQUEST_REGISTER and value == VALUE_BUF_ENDACCESS:
        return describe_0x8c(setup, data)
    return None


def is_register_read(setup: dict) -> bool:
    return (setup["bRequest"] == REQUEST_BUFFER
            and setup["wValue"] & 0xFF == VALUE_GET_REGISTER
            and setup["wIndex"] & 0xFF == REGISTER_READ_INDEX_BASE
            and setup["wLength"] == 2)


def classify_vendor_in(setup: dict, data: bytes) -> Optional[tuple[str, str]]:
    if is_register_read(setup):
        return describe_register_read(setup, data)
    if setup["bRequest"] == REQUEST_REGISTER and setup["wValue"] == VALUE_GET_REGISTER:
        return describe_request_read(setup, data)
    return None


def describe_control(transaction: Transaction) -> tuple[str, str]:
    setup = transaction.submit.get("setup") if transaction.submit else None
    if setup is None:
        return "other", "control completion without request"
    out_data, in_data = submit_data(transaction), completion_data(transaction)
    request_type = setup["bmRequestType"]
    if request_type & 0x60 == 0:
        return describe_standard(setup, in_data)
    known = None
    if request_type == REQUEST_TYPE_VENDOR_OUT:
        known = classify_vendor_out(setup, out_data)
    elif request_type == REQUEST_TYPE_VENDOR_IN:
        known = classify_vendor_in(setup, in_data)
    return known or describe_other_control(setup, out_data, in_data)


# --- bulk and interrupt -------------------------------------------------------


def transfer_bytes(transaction: Transaction) -> tuple[int, str]:
    """(byte count, leading data hex) of a bulk or interrupt transfer."""
    record = transaction.complete if first_record(transaction)["direction"] == "in" \
        else transaction.submit
    if record is None:
        return 0, ""
    return record["data_length"], record["data_hex"]


def describe_bulk(transaction: Transaction) -> tuple[str, str, int]:
    record = first_record(transaction)
    size, leading_hex = transfer_bytes(transaction)
    kind = "bulk_in" if record["direction"] == "in" else "bulk_out"
    label = "IN" if kind == "bulk_in" else "OUT"
    text = "bulk %s 0x%02x %d bytes: %s" % (label, record["endpoint"], size, leading_hex[:64])
    return kind, text, size


def describe_interrupt(transaction: Transaction) -> tuple[str, str]:
    record = first_record(transaction)
    _, data_hex = transfer_bytes(transaction)
    return "interrupt", "interrupt IN 0x%02x -> %s" % (record["endpoint"], data_hex or "(none)")


def describe(transaction: Transaction) -> Operation:
    record = first_record(transaction)
    first, last = frame_range(transaction)
    byte_total = 0
    if record["transfer_type"] == "control":
        kind, text = describe_control(transaction)
    elif record["transfer_type"] == "bulk":
        kind, text, byte_total = describe_bulk(transaction)
    elif record["transfer_type"] == "interrupt":
        kind, text = describe_interrupt(transaction)
    else:
        kind, text = "other", "%s transfer" % record["transfer_type"]
    text += status_suffix(transaction)
    return Operation(first, last, record["relative_time"], kind, text,
                     record["endpoint"], byte_total)


# --- folding passes -------------------------------------------------------------


def is_link_check(operation: Operation) -> bool:
    return operation.text == "request read wIndex 0x%02x -> 0x%02x" % (LINK_CHECK_INDEX, LINK_OK)


def fold_link_checks(operations: list[Operation]) -> list[Operation]:
    """Attach a passing link check to the control operation right before it."""
    folded: list[Operation] = []
    for operation in operations:
        previous = folded[-1] if folded else None
        if is_link_check(operation) and previous and previous.kind not in ("bulk_in", "bulk_out", "interrupt"):
            previous.text += " | link 0x55"
            previous.last_frame = operation.last_frame
            continue
        folded.append(operation)
    return folded


def merge_bulk_runs(operations: list[Operation]) -> list[Operation]:
    """Join consecutive bulk transfers on one endpoint into one operation."""
    merged: list[Operation] = []
    for operation in operations:
        previous = merged[-1] if merged else None
        same_run = (previous is not None and operation.kind in ("bulk_in", "bulk_out")
                    and previous.kind == operation.kind and previous.endpoint == operation.endpoint)
        if not same_run:
            merged.append(dataclasses.replace(operation))
            continue
        previous.count += 1
        previous.byte_total += operation.byte_total
        previous.last_frame = operation.last_frame
    for operation in merged:
        if operation.kind in ("bulk_in", "bulk_out") and operation.count > 1:
            label = "IN" if operation.kind == "bulk_in" else "OUT"
            operation.text = "bulk %s 0x%02x: %d transfers, %d bytes" % (
                label, operation.endpoint, operation.count, operation.byte_total)
            operation.count = 1
    return merged


def compress_repeats(operations: list[Operation]) -> list[Operation]:
    """Fold runs of identical operations into one line with a count."""
    compressed: list[Operation] = []
    for operation in operations:
        previous = compressed[-1] if compressed else None
        if previous is not None and previous.text == operation.text:
            previous.count += 1
            previous.last_frame = operation.last_frame
            continue
        compressed.append(dataclasses.replace(operation))
    return compressed


# --- output ---------------------------------------------------------------------


def format_operation(operation: Operation) -> str:
    time = "%10.4f" % operation.time if operation.time is not None else " " * 10
    repeat = "" if operation.count == 1 else "  (x%d)" % operation.count
    return "%6d-%-6d %s  %s%s" % (operation.first_frame, operation.last_frame, time,
                                  operation.text, repeat)


def annotate(records: Iterable[dict]) -> list[str]:
    operations = [describe(transaction) for transaction in pair_transactions(records)]
    operations = compress_repeats(fold_link_checks(merge_bulk_runs(operations)))
    return [format_operation(operation) for operation in operations]


def read_records(lines: Iterable[str]) -> Iterable[dict]:
    return (json.loads(line) for line in lines if line.strip())


def main(arguments: list[str]) -> int:
    source = open(arguments[0]) if arguments else sys.stdin
    with source:
        for line in annotate(read_records(source)):
            sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
