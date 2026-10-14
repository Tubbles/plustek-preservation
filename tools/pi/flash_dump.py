"""Read the OpticFilm 120's serial flash over USB, read-only.

Uses the requests Plustek's driver sends at every open
(doc/protocol/serial-flash.md, doc/protocol/of120-capture-151.md set C):
SPI init (two small writes to the ASIC's SPI controller), JEDEC ID read,
then per 64-byte block an address write and a data read. Framing follows
the Windows capture: bRequest 0x0c for one-byte transfers, 0x04 for longer
ones.

The only OUT requests this tool can send are the three listed in
ALLOWED_WRITES, checked before every transfer. The flash program and
erase requests (0x8b with wIndex 0x0f, 0x10, 0x11, 0x12) are refused.

Sequence:
1. Refuse to start unless the file probe-disabled exists next to this
   script (it stops watch-scanner.sh from starting the probe on a wake) and
   neither probe_readonly.py nor keep_awake.py runs. Create the file before
   the wake and start the dump after the watcher has logged "probe
   disabled" for the connection, so that its lsusb and keep_awake.py runs
   are over.
2. Read registers 0x31 (GPIO8, the standby line), 0x34 (GPOE8, its output
   enable, is bit 7) and 0x36 (GPOE17 to 24) and log them.
3. SPI init and JEDEC ID. Stop unless the ID decodes to 64 KiB to 512 KiB
   (the working unit's chip is c2 20 13, 512 KiB).
4. Address check on the first 128 bytes (see verify_addressing). Stop when
   the ASIC does not apply the address as sent.
5. Two full passes, the second in descending address order, so that a
   fault that depends on read order cannot give two identical wrong images.
6. Check the image for address aliasing: an ASIC that drops address bit k
   makes every block equal to its partner at address XOR 2^k.

Exit 0 means the passes agree, the image is not uniform and no address
bit aliases. It does not prove the address decoding right: a decoder that
permutes address bits without dropping any would still pass.

Every run writes to a new timestamped directory under OUTPUT_DIRECTORY:
pass1.bin, pass2.bin (both in address order) and log.jsonl. Every block is
flushed as it arrives, so a pass cut short keeps what it read; the part
of pass 2 it never reached reads as zeros.

Exit codes (1 and 2 are left to Python and argparse): 0 good dump (or ID
read with --id-only), 10 scanner not found, 11 unusable JEDEC ID, 12
passes differ, 13 USB error, short transfer or refused request, 14
addressing check failed, 15 both passes uniform (all ff or all 00: a blank
flash and a stuck data path look the same), 16 probe not disabled or still
running, 17 the image repeats across an address bit (a dropped address
bit, or content that really is duplicated: check by hand).

Usage (on the Pi):
    sudo ~/plustek-preservation/venv/bin/python flash_dump.py OUTPUT_DIRECTORY [--id-only]
"""

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import struct
import sys
import typing

import usb.core

KNOWN_IDENTITIES = ((0x05E3, 0x0103), (0x07B3, 0x1406))
TIMEOUT_MILLISECONDS = 1000
BLOCK_SIZE = 64
FLASH_READ_VALUE = 0x008A
FLASH_WRITE_VALUE = 0x008B
SPI_ENABLE_INDEX = 0x07
SPI_SETUP_INDEX = 0x09
ADDRESS_INDEX = 0x0B
DATA_INDEX = 0x0F
JEDEC_ID_INDEX = 0x10
ALLOWED_WRITES = {SPI_ENABLE_INDEX: 1, SPI_SETUP_INDEX: 4, ADDRESS_INDEX: 4}
REFUSED_WRITE_INDICES = (DATA_INDEX, JEDEC_ID_INDEX, 0x11, 0x12)
ALLOWED_FLASH_READS = {JEDEC_ID_INDEX: 3, DATA_INDEX: BLOCK_SIZE}
SMALLEST_CAPACITY_CODE = 0x10
LARGEST_CAPACITY_CODE = 0x13
OTHER_SCANNER_SCRIPTS = (b"probe_readonly.py", b"keep_awake.py")

EXIT_GOOD = 0
EXIT_NOT_FOUND = 10
EXIT_BAD_JEDEC_ID = 11
EXIT_PASSES_DIFFER = 12
EXIT_USB_ERROR = 13
EXIT_ADDRESSING = 14
EXIT_UNIFORM = 15
EXIT_PROBE_ACTIVE = 16
EXIT_ALIASED = 17


@dataclasses.dataclass
class Session:
    device: typing.Any
    log_file: typing.TextIO


class ShortTransferError(Exception):
    pass


def request_code_for(length: int) -> int:
    return 0x0C if length == 1 else 0x04


def utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def log(session: Session, record: dict) -> None:
    line = json.dumps({"time": utc_timestamp(), **record})
    session.log_file.write(line + "\n")
    session.log_file.flush()
    print(line, flush=True)


def check_write_allowed(index: int, data: bytes, flash_size: int) -> None:
    """Raise unless (index, data) is one of the three known harmless writes."""
    if index in REFUSED_WRITE_INDICES or index not in ALLOWED_WRITES:
        raise PermissionError(f"refusing write to wIndex 0x{index:02x}")
    if len(data) != ALLOWED_WRITES[index]:
        raise PermissionError(f"wrong length {len(data)} for wIndex 0x{index:02x}")
    if index == SPI_ENABLE_INDEX and data != b"\x01":
        raise PermissionError("SPI enable must be 01")
    if index == SPI_SETUP_INDEX and data != bytes(4):
        raise PermissionError("SPI set-up must be 00 00 00 00")
    if index == ADDRESS_INDEX:
        address = struct.unpack("<I", data)[0]
        if address % BLOCK_SIZE or address >= flash_size:
            raise PermissionError(f"address 0x{address:x} outside the flash or unaligned")


def control_in(session: Session, request: int, value: int, index: int, length: int) -> bytes:
    """Vendor IN transfer that fails on a short answer (pyusb returns short data silently)."""
    data = bytes(session.device.ctrl_transfer(0xC0, request, value, index, length, TIMEOUT_MILLISECONDS))
    if len(data) != length:
        raise ShortTransferError(f"wValue 0x{value:04x} wIndex 0x{index:04x}: got {len(data)} of {length} bytes")
    return data


def link_check(session: Session) -> str:
    return control_in(session, 0x0C, 0x008E, 0x0020, 1).hex()


def read_register(session: Session, register: int) -> str:
    """GL124/GL128 register read framing, the same as probe_readonly.py."""
    value = 0x018E if register > 0xFF else 0x008E
    index = 0x22 + ((register & 0xFF) << 8)
    return control_in(session, 0x04, value, index, 2).hex(" ")


def flash_write(session: Session, index: int, data: bytes, flash_size: int) -> str:
    check_write_allowed(index, data, flash_size)
    written = session.device.ctrl_transfer(0x40, request_code_for(len(data)), FLASH_WRITE_VALUE, index,
                                           data, TIMEOUT_MILLISECONDS)
    if written != len(data):
        raise ShortTransferError(f"write to wIndex 0x{index:02x}: sent {written} of {len(data)} bytes")
    return link_check(session)


def flash_read(session: Session, index: int) -> bytes:
    if index not in ALLOWED_FLASH_READS:
        raise PermissionError(f"refusing flash read with wIndex 0x{index:02x}")
    length = ALLOWED_FLASH_READS[index]
    return control_in(session, request_code_for(length), FLASH_READ_VALUE, index, length)


def spi_init(session: Session) -> None:
    for index, data in ((SPI_ENABLE_INDEX, b"\x01"), (SPI_SETUP_INDEX, bytes(4))):
        log(session, {"kind": "spi_init", "index": f"{index:02x}",
                      "link_check": flash_write(session, index, data, flash_size=0)})


def flash_size_from_jedec_id(jedec_id: bytes) -> int:
    """Capacity code is log2 of the size in bytes for Macronix and most others; 0 if unusable."""
    capacity_code = jedec_id[2]
    if jedec_id[0] in (0x00, 0xFF) or not SMALLEST_CAPACITY_CODE <= capacity_code <= LARGEST_CAPACITY_CODE:
        return 0
    return 1 << capacity_code


def read_block(session: Session, address: int, flash_size: int) -> bytes:
    flash_write(session, ADDRESS_INDEX, struct.pack("<I", address), flash_size)
    return flash_read(session, DATA_INDEX)


def classify_addressing(first: bytes, incremented: bytes, direct: bytes) -> str:
    """Judge one address write at 0 plus two reads against a direct read at 0x40."""
    if first == incremented == direct and uniform_value(first) is not None:
        return "inconclusive_uniform"
    if first == direct:
        return "address_ignored"
    if incremented == direct:
        return "consistent"
    if incremented == first:
        return "no_auto_increment"
    return "inconsistent"


def verify_addressing(session: Session, flash_size: int) -> bool:
    """Check that a non-zero LE32 address is applied as sent, before trusting a full dump.

    The full dump writes the address before every block, so a missing
    auto-increment does not matter. An ignored address, or reads that fit
    neither model, stop the tool. A uniform start (all ff or all 00) is
    logged as inconclusive and the dump goes on: the descending second pass
    and the aliasing check still catch an ignored or truncated address
    unless the whole image is uniform.
    """
    flash_write(session, ADDRESS_INDEX, struct.pack("<I", 0), flash_size)
    first = flash_read(session, DATA_INDEX)
    incremented = flash_read(session, DATA_INDEX)
    direct = read_block(session, BLOCK_SIZE, flash_size)
    verdict = classify_addressing(first, incremented, direct)
    log(session, {"kind": "addressing_check", "verdict": verdict, "block_0": first.hex(),
                  "block_40_incremented": incremented.hex(), "block_40_direct": direct.hex()})
    return verdict not in ("address_ignored", "inconsistent")


def read_pass(session: Session, flash_size: int, pass_number: int, addresses: list, pass_file) -> dict:
    """Read the given blocks in order, writing each to pass_file at its own offset."""
    blocks = {}
    for count, address in enumerate(addresses):
        block = read_block(session, address, flash_size)
        pass_file.seek(address)
        pass_file.write(block)
        pass_file.flush()
        blocks[address] = block
        if count % 1024 == 0:
            log(session, {"kind": "progress", "pass": pass_number, "address": f"{address:06x}"})
    return blocks


def assemble(blocks: dict, flash_size: int) -> bytes:
    return b"".join(blocks[address] for address in range(0, flash_size, BLOCK_SIZE))


def differing_blocks(first: bytes, second: bytes) -> list:
    return [f"{address:06x}" for address in range(0, len(first), BLOCK_SIZE)
            if first[address:address + BLOCK_SIZE] != second[address:address + BLOCK_SIZE]]


def uniform_value(image: bytes) -> typing.Optional[int]:
    """0xff or 0x00 when the whole image is that one value, else None."""
    for value in (0xFF, 0x00):
        if image == bytes([value]) * len(image):
            return value
    return None


def aliased_address_bits(image: bytes) -> list:
    """Address bits k, from the block size up, where every block equals the one at address XOR 2^k."""
    bits = []
    for bit in range(BLOCK_SIZE.bit_length() - 1, len(image).bit_length() - 1):
        stride = 1 << bit
        if all(image[base:base + stride] == image[base + stride:base + 2 * stride]
               for base in range(0, len(image), 2 * stride)):
            bits.append(bit)
    return bits


def summarise(image: bytes) -> dict:
    return {"sha256": hashlib.sha256(image).hexdigest(),
            "bytes_not_ff": sum(1 for value in image if value != 0xFF),
            "bytes_not_00": sum(1 for value in image if value != 0x00)}


def dump(session: Session, output_directory: pathlib.Path, id_only: bool) -> int:
    log(session, {"kind": "registers", "0x31": read_register(session, 0x31),
                  "0x34": read_register(session, 0x34), "0x36": read_register(session, 0x36)})
    spi_init(session)
    jedec_id = flash_read(session, JEDEC_ID_INDEX)
    log(session, {"kind": "jedec_id_raw", "returned": jedec_id.hex(" ")})
    flash_size = flash_size_from_jedec_id(jedec_id)
    log(session, {"kind": "jedec_id", "flash_size": flash_size})
    if flash_size == 0:
        return EXIT_BAD_JEDEC_ID
    if id_only:
        return EXIT_GOOD
    if not verify_addressing(session, flash_size):
        return EXIT_ADDRESSING
    ascending = list(range(0, flash_size, BLOCK_SIZE))
    images = []
    for pass_number, addresses in ((1, ascending), (2, ascending[::-1])):
        with open(output_directory / f"pass{pass_number}.bin", "wb") as pass_file:
            image = assemble(read_pass(session, flash_size, pass_number, addresses, pass_file), flash_size)
        log(session, {"kind": "pass_done", "pass": pass_number, **summarise(image)})
        images.append(image)
    mismatches = differing_blocks(images[0], images[1])
    log(session, {"kind": "compare", "differing_blocks": mismatches})
    if mismatches:
        return EXIT_PASSES_DIFFER
    value = uniform_value(images[0])
    if value is not None:
        log(session, {"kind": "uniform_image", "value": f"{value:02x}",
                      "note": "a blank flash and a stuck data path look the same"})
        return EXIT_UNIFORM
    aliased_bits = aliased_address_bits(images[0])
    log(session, {"kind": "aliasing_check", "aliased_address_bits": aliased_bits})
    if aliased_bits:
        return EXIT_ALIASED
    return EXIT_GOOD


def run(session: Session, run_directory: pathlib.Path, id_only: bool) -> int:
    """dump() with transfer errors and refused requests logged and mapped to an exit code."""
    try:
        exit_code = dump(session, run_directory, id_only)
    except (usb.core.USBError, PermissionError, ShortTransferError) as error:
        log(session, {"kind": "error", "error": str(error)})
        exit_code = EXIT_USB_ERROR
    log(session, {"kind": "exit", "code": exit_code})
    return exit_code


def probe_is_running(proc_root: pathlib.Path) -> bool:
    """True when any process has probe_readonly.py or keep_awake.py among its arguments."""
    for cmdline in proc_root.glob("[0-9]*/cmdline"):
        try:
            arguments = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        if any(argument.endswith(OTHER_SCANNER_SCRIPTS) for argument in arguments):
            return True
    return False


def find_scanner():
    for vendor_id, product_id in KNOWN_IDENTITIES:
        device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if device is not None:
            return device
    return None


def new_run_directory(output_directory: pathlib.Path) -> pathlib.Path:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_directory = output_directory / stamp
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Read the scanner's serial flash over USB.")
    parser.add_argument("output_directory", type=pathlib.Path)
    parser.add_argument("--id-only", action="store_true", help="stop after the JEDEC ID read")
    arguments = parser.parse_args()
    probe_disabled = pathlib.Path(__file__).resolve().parent / "probe-disabled"
    if not probe_disabled.exists() or probe_is_running(pathlib.Path("/proc")):
        print(f"create {probe_disabled} and wait until no probe_readonly.py or keep_awake.py runs",
              file=sys.stderr)
        return EXIT_PROBE_ACTIVE
    device = find_scanner()
    if device is None:
        print("scanner not found", file=sys.stderr)
        return EXIT_NOT_FOUND
    run_directory = new_run_directory(arguments.output_directory)
    print(f"output in {run_directory}", flush=True)
    with open(run_directory / "log.jsonl", "w") as log_file:
        session = Session(device, log_file)
        log(session, {"kind": "device", "vendor_id": f"{device.idVendor:04x}",
                      "product_id": f"{device.idProduct:04x}", "bcd_device": f"{device.bcdDevice:04x}"})
        return run(session, run_directory, arguments.id_only)


if __name__ == "__main__":
    sys.exit(main())
