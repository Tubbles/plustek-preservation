#!/usr/bin/env python3
"""Decode USBPcap captures into one JSON object per captured USB record.

Reads Windows USBPcap captures (link type 249) stored as classic pcap or as
pcapng and prints one JSON object per line. Each USB request appears at
least twice in such a capture: when the host submits it and when it
completes. The "event" field says which one a line is ("submit" or
"complete"), and the "irp_id" field links them.

Usage: decode.py <capture> [--device <address>]

Header layout (https://desowin.org/usbpcap/captureformat.html): a packed
little-endian header of 27 bytes (header length, IRP id, USBD status, URB
function, info, bus, device, endpoint, transfer type, data length), one
stage byte more for control transfers, then the data. Info bit 0 is set on
the way back from the device, i.e. on the completion.

Control transfers, per the same page: USBPcap 1.5.0.0 and later write two
records, a setup stage holding the 8-byte setup packet followed by any OUT
data, and a complete stage holding any IN data. Earlier versions write a
setup stage with the setup packet only, an optional data stage with the OUT
or IN data, and a status stage on completion. Records are printed as they
are, with control_stage naming the stage.

Data is kept in full for control transfers. Bulk and interrupt data longer
than 64 bytes is cut to its first 64 bytes, with data_truncated and
captured_sha256 added. data_length is the length the USBPcap header
declares. When the capture holds fewer bytes (cut at the snapshot length),
captured_length gives how many, and captured_sha256 covers only those.

A file that ends in the middle of a record, or whose structure is
inconsistent, is reported on stderr with exit status 1, after the records
before the fault have been printed.
"""

import argparse
import dataclasses
import hashlib
import json
import mmap
import os
import struct
import sys
from typing import Iterator, Optional

LINK_TYPE_USBPCAP = 249

PCAP_MAGIC_MICROSECONDS = 0xA1B2C3D4
PCAP_MAGIC_NANOSECONDS = 0xA1B23C4D
PCAP_GLOBAL_HEADER_LENGTH = 24
PCAP_RECORD_HEADER_LENGTH = 16

PCAPNG_SECTION_HEADER_BLOCK = 0x0A0D0D0A
PCAPNG_INTERFACE_DESCRIPTION_BLOCK = 1
PCAPNG_SIMPLE_PACKET_BLOCK = 3
PCAPNG_ENHANCED_PACKET_BLOCK = 6
PCAPNG_BYTE_ORDER_MAGIC = 0x1A2B3C4D
PCAPNG_OPTION_END = 0
PCAPNG_OPTION_TIMESTAMP_RESOLUTION = 9
PCAPNG_DEFAULT_TIMESTAMP_RESOLUTION = 6

USBPCAP_HEADER_FORMAT = "<HQIHBHHBBI"
USBPCAP_HEADER_LENGTH = struct.calcsize(USBPCAP_HEADER_FORMAT)
USBPCAP_INFO_PDO_TO_FDO = 0x01
USBPCAP_TRANSFER_CONTROL = 2
USBPCAP_CONTROL_STAGE_SETUP = 0

SETUP_PACKET_LENGTH = 8
INLINE_DATA_LIMIT = 64

TRANSFER_TYPE_NAMES = {0: "isochronous", 1: "interrupt", 2: "control", 3: "bulk"}

CONTROL_STAGE_NAMES = {0: "setup", 1: "data", 2: "status", 3: "complete"}


class CaptureFormatError(ValueError):
    """The file is not a capture this tool can read, or it is cut short."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFormatError(message)


@dataclasses.dataclass(frozen=True)
class CaptureRecord:
    """One packet record from the capture file, before USBPcap decoding."""

    frame_number: int
    timestamp: Optional[float]
    link_type: int
    payload: bytes


@dataclasses.dataclass(frozen=True)
class UsbPcapHeader:
    """The USBPcap pseudo header in front of every USB record."""

    header_length: int
    irp_id: int
    usbd_status: int
    urb_function: int
    info: int
    bus: int
    device: int
    endpoint: int
    transfer_type: int
    data_length: int
    control_stage: Optional[int]


@dataclasses.dataclass(frozen=True)
class SetupPacket:
    """The 8-byte setup packet of a control transfer."""

    request_type: int
    request: int
    value: int
    index: int
    length: int


@dataclasses.dataclass(frozen=True)
class PcapngInterface:
    """What an interface description block says about its packets."""

    link_type: int
    timestamp_resolution: float


# --- classic pcap -----------------------------------------------------------


def pcap_layout(magic_bytes: bytes) -> Optional[tuple[str, float]]:
    """Return (struct byte order, seconds per fraction unit) for a pcap magic."""
    for byte_order in ("<", ">"):
        magic = struct.unpack(byte_order + "I", magic_bytes)[0]
        if magic == PCAP_MAGIC_MICROSECONDS:
            return byte_order, 1e-6
        if magic == PCAP_MAGIC_NANOSECONDS:
            return byte_order, 1e-9
    return None


def pcap_link_type(buffer: bytes, byte_order: str) -> int:
    """Link type from the pcap global header (low 16 bits of the field)."""
    network = struct.unpack_from(byte_order + "I", buffer, 20)[0]
    return network & 0xFFFF


def iterate_pcap_records(buffer: bytes) -> Iterator[CaptureRecord]:
    """Yield every packet record of a classic pcap file."""
    require(len(buffer) >= PCAP_GLOBAL_HEADER_LENGTH,
            "truncated pcap file header: %d of %d bytes"
            % (len(buffer), PCAP_GLOBAL_HEADER_LENGTH))
    byte_order, fraction_unit = pcap_layout(buffer[0:4])
    link_type = pcap_link_type(buffer, byte_order)
    offset = PCAP_GLOBAL_HEADER_LENGTH
    frame_number = 0
    while offset < len(buffer):
        frame_number += 1
        require(offset + PCAP_RECORD_HEADER_LENGTH <= len(buffer),
                "frame %d: truncated pcap record header at byte %d" % (frame_number, offset))
        seconds, fraction, captured_length, _ = struct.unpack_from(
            byte_order + "IIII", buffer, offset)
        offset += PCAP_RECORD_HEADER_LENGTH
        require(offset + captured_length <= len(buffer),
                "frame %d: truncated pcap record, %d bytes declared, %d left in the file"
                % (frame_number, captured_length, len(buffer) - offset))
        payload = bytes(buffer[offset:offset + captured_length])
        offset += captured_length
        timestamp = seconds + fraction * fraction_unit
        yield CaptureRecord(frame_number, timestamp, link_type, payload)


# --- pcapng -----------------------------------------------------------------


def pcapng_section_byte_order(buffer: bytes, block_offset: int) -> str:
    """Byte order of a section, from the magic in its section header block."""
    for byte_order in ("<", ">"):
        if struct.unpack_from(byte_order + "I", buffer, block_offset + 8)[0] \
                == PCAPNG_BYTE_ORDER_MAGIC:
            return byte_order
    raise CaptureFormatError("section header block at byte %d has no byte-order magic"
                             % block_offset)


def pcapng_options(body: bytes, byte_order: str) -> dict[int, bytes]:
    """Parse a pcapng option list into {option code: raw value}."""
    options = {}
    offset = 0
    while offset + 4 <= len(body):
        code, length = struct.unpack_from(byte_order + "HH", body, offset)
        if code == PCAPNG_OPTION_END:
            break
        options[code] = bytes(body[offset + 4:offset + 4 + length])
        offset += 4 + (length + 3) // 4 * 4
    return options


def timestamp_resolution(resolution_byte: int) -> float:
    """Seconds per timestamp unit for an if_tsresol option byte."""
    exponent = resolution_byte & 0x7F
    if resolution_byte & 0x80:
        return 2.0 ** -exponent
    return 10.0 ** -exponent


def parse_interface_block(body: bytes, byte_order: str) -> PcapngInterface:
    """Read link type and timestamp resolution from an interface block."""
    require(len(body) >= 8, "interface description block shorter than 8 bytes")
    link_type = struct.unpack_from(byte_order + "H", body, 0)[0]
    options = pcapng_options(body[8:], byte_order)
    resolution_option = options.get(PCAPNG_OPTION_TIMESTAMP_RESOLUTION)
    resolution_byte = (resolution_option[0] if resolution_option
                       else PCAPNG_DEFAULT_TIMESTAMP_RESOLUTION)
    return PcapngInterface(link_type, timestamp_resolution(resolution_byte))


def parse_enhanced_packet(body: bytes, byte_order: str,
                          interfaces: list[PcapngInterface],
                          frame_number: int) -> CaptureRecord:
    """Turn an enhanced packet block body into a capture record."""
    require(len(body) >= 20, "frame %d: enhanced packet block shorter than 20 bytes"
            % frame_number)
    interface_id, high, low, captured_length, _ = struct.unpack_from(
        byte_order + "IIIII", body, 0)
    require(interface_id < len(interfaces),
            "frame %d: packet refers to interface %d, but %d interface description "
            "blocks precede it" % (frame_number, interface_id, len(interfaces)))
    require(20 + captured_length <= len(body),
            "frame %d: packet data longer than its block" % frame_number)
    interface = interfaces[interface_id]
    timestamp = ((high << 32) | low) * interface.timestamp_resolution
    payload = bytes(body[20:20 + captured_length])
    return CaptureRecord(frame_number, timestamp, interface.link_type, payload)


def parse_simple_packet(body: bytes, byte_order: str,
                        interfaces: list[PcapngInterface],
                        frame_number: int) -> CaptureRecord:
    """Turn a simple packet block body (no timestamp) into a capture record."""
    require(len(body) >= 4, "frame %d: simple packet block shorter than 4 bytes"
            % frame_number)
    require(len(interfaces) > 0,
            "frame %d: simple packet block before any interface description block"
            % frame_number)
    original_length = struct.unpack_from(byte_order + "I", body, 0)[0]
    payload = bytes(body[4:4 + original_length])
    return CaptureRecord(frame_number, None, interfaces[0].link_type, payload)


def iterate_pcapng_records(buffer: bytes) -> Iterator[CaptureRecord]:
    """Yield every packet record of a pcapng file, numbered like Wireshark."""
    byte_order = "<"
    interfaces: list[PcapngInterface] = []
    offset = 0
    frame_number = 0
    while offset < len(buffer):
        require(offset + 12 <= len(buffer),
                "truncated pcapng block at byte %d: %d bytes left"
                % (offset, len(buffer) - offset))
        block_type = struct.unpack_from(byte_order + "I", buffer, offset)[0]
        if block_type == PCAPNG_SECTION_HEADER_BLOCK:
            byte_order = pcapng_section_byte_order(buffer, offset)
            interfaces = []
        block_length = struct.unpack_from(byte_order + "I", buffer, offset + 4)[0]
        require(block_length >= 12, "pcapng block at byte %d has length %d"
                % (offset, block_length))
        require(offset + block_length <= len(buffer),
                "truncated pcapng block at byte %d: length %d, %d bytes left"
                % (offset, block_length, len(buffer) - offset))
        body = buffer[offset + 8:offset + block_length - 4]
        offset += block_length
        if block_type == PCAPNG_INTERFACE_DESCRIPTION_BLOCK:
            interfaces.append(parse_interface_block(body, byte_order))
        elif block_type == PCAPNG_ENHANCED_PACKET_BLOCK:
            frame_number += 1
            yield parse_enhanced_packet(body, byte_order, interfaces, frame_number)
        elif block_type == PCAPNG_SIMPLE_PACKET_BLOCK:
            frame_number += 1
            yield parse_simple_packet(body, byte_order, interfaces, frame_number)


def iterate_capture_records(buffer: bytes) -> Iterator[CaptureRecord]:
    """Dispatch on the file magic: classic pcap or pcapng."""
    require(len(buffer) >= 4, "file too short for a capture: %d bytes" % len(buffer))
    if struct.unpack_from("<I", buffer, 0)[0] == PCAPNG_SECTION_HEADER_BLOCK:
        return iterate_pcapng_records(buffer)
    if pcap_layout(buffer[0:4]) is not None:
        return iterate_pcap_records(buffer)
    raise CaptureFormatError("not a pcap or pcapng file")


# --- USBPcap ----------------------------------------------------------------


def parse_usbpcap_header(payload: bytes) -> Optional[UsbPcapHeader]:
    """Decode the USBPcap pseudo header, or None if the record is too short."""
    if len(payload) < USBPCAP_HEADER_LENGTH:
        return None
    fields = struct.unpack_from(USBPCAP_HEADER_FORMAT, payload, 0)
    header_length, transfer_type = fields[0], fields[8]
    has_stage = (transfer_type == USBPCAP_TRANSFER_CONTROL
                 and header_length > USBPCAP_HEADER_LENGTH
                 and len(payload) > USBPCAP_HEADER_LENGTH)
    control_stage = payload[USBPCAP_HEADER_LENGTH] if has_stage else None
    return UsbPcapHeader(*fields, control_stage)


def parse_setup_packet(data: bytes) -> SetupPacket:
    """Decode the first 8 bytes of a control setup stage."""
    return SetupPacket(*struct.unpack_from("<BBHHH", data, 0))


def is_setup_stage(header: UsbPcapHeader, data: bytes) -> bool:
    return (header.control_stage == USBPCAP_CONTROL_STAGE_SETUP
            and header.data_length >= SETUP_PACKET_LENGTH
            and len(data) >= SETUP_PACKET_LENGTH)


def split_record_data(header: UsbPcapHeader, payload: bytes
                      ) -> tuple[Optional[SetupPacket], bytes, int]:
    """Return (setup packet or None, transfer data, declared data length).

    A setup-stage record starts with the 8-byte setup packet, which is split
    off. From USBPcap 1.5.0.0 on, any OUT data follows it in the same record
    and is reported as data. Earlier versions put the data in a separate
    data-stage record, which is reported as it is.
    """
    data = payload[header.header_length:header.header_length + header.data_length]
    if not is_setup_stage(header, data):
        return None, data, header.data_length
    setup = parse_setup_packet(data)
    declared_length = header.data_length - SETUP_PACKET_LENGTH
    return setup, data[SETUP_PACKET_LENGTH:], declared_length


def data_fields(data: bytes, keep_all: bool) -> dict:
    """Hex of the captured data, cut to INLINE_DATA_LIMIT bytes unless keep_all.

    A cut adds data_truncated and captured_sha256, the sha256 of all captured
    bytes (which are fewer than declared when the capture's snapshot length
    cut the record).
    """
    if keep_all or len(data) <= INLINE_DATA_LIMIT:
        return {"data_hex": data.hex()}
    return {
        "data_hex": data[:INLINE_DATA_LIMIT].hex(),
        "data_truncated": True,
        "captured_sha256": hashlib.sha256(data).hexdigest(),
    }


def setup_fields(setup: SetupPacket) -> dict:
    return {
        "bmRequestType": setup.request_type,
        "bRequest": setup.request,
        "wValue": setup.value,
        "wIndex": setup.index,
        "wLength": setup.length,
    }


def transfer_object(record: CaptureRecord, header: UsbPcapHeader,
                    first_timestamp: Optional[float]) -> dict:
    """Build the JSON object for one USBPcap record."""
    setup, data, declared_length = split_record_data(header, record.payload)
    is_control = header.transfer_type == USBPCAP_TRANSFER_CONTROL
    relative_time = (None if record.timestamp is None or first_timestamp is None
                     else round(record.timestamp - first_timestamp, 6))
    transfer = {
        "frame": record.frame_number,
        "timestamp": record.timestamp,
        "relative_time": relative_time,
        "bus": header.bus,
        "device": header.device,
        "endpoint": header.endpoint,
        "transfer_type": TRANSFER_TYPE_NAMES.get(header.transfer_type,
                                                 str(header.transfer_type)),
        "direction": "in" if header.endpoint & 0x80 else "out",
        "event": "complete" if header.info & USBPCAP_INFO_PDO_TO_FDO else "submit",
        "irp_id": "0x%016x" % header.irp_id,
        "usbd_status": header.usbd_status,
        "urb_function": header.urb_function,
    }
    if header.control_stage is not None:
        transfer["control_stage"] = CONTROL_STAGE_NAMES.get(
            header.control_stage, str(header.control_stage))
    if setup is not None:
        transfer["setup"] = setup_fields(setup)
    transfer["data_length"] = declared_length
    if len(data) != declared_length:
        transfer["captured_length"] = len(data)
    transfer.update(data_fields(data, keep_all=is_control))
    return transfer


def iterate_transfers(buffer: bytes, device_filter: Optional[int]) -> Iterator[dict]:
    """Yield the JSON objects of all USBPcap records, optionally one device only."""
    first_timestamp = None
    for record in iterate_capture_records(buffer):
        if first_timestamp is None:
            first_timestamp = record.timestamp
        if record.link_type != LINK_TYPE_USBPCAP:
            continue
        header = parse_usbpcap_header(record.payload)
        if header is None:
            continue
        if device_filter is not None and header.device != device_filter:
            continue
        yield transfer_object(record, header, first_timestamp)


# --- command line -----------------------------------------------------------


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print USBPcap records of a pcap/pcapng capture as JSON lines.")
    parser.add_argument("capture", help="path to a .pcap or .pcapng file")
    parser.add_argument("--device", type=int, default=None,
                        help="only records of this USB device address")
    return parser.parse_args(arguments)


def map_file(path: str):
    """Memory-map a capture read-only (an empty file maps to b'')."""
    with open(path, "rb") as capture_file:
        if os.fstat(capture_file.fileno()).st_size == 0:
            return b""
        return mmap.mmap(capture_file.fileno(), 0, access=mmap.ACCESS_READ)


def main(arguments: list[str]) -> int:
    options = parse_arguments(arguments)
    buffer = map_file(options.capture)
    try:
        for transfer in iterate_transfers(buffer, options.device):
            sys.stdout.write(json.dumps(transfer) + "\n")
        sys.stdout.flush()
    except CaptureFormatError as error:
        sys.stdout.flush()
        sys.stderr.write("%s: %s\n" % (options.capture, error))
        return 1
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
