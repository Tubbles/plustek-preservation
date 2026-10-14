"""Read a serial EEPROM through the OpticFilm 120's ASIC registers, read-only.

Follows CAsic::ReadFromNVRAM of Plustek's macOS engine (0x061120, never
called by the engine, see doc/protocol/serial-eeprom.md), without its EWEN.
Register framing as in the Windows capture: write 40 04 0083 wIndex 0 with
[register, value], read c0 04 008e wIndex 0x22 + (register << 8), 2 bytes,
answer [value, 0x55].

The 0x8b values are Microwire commands of a 93C46 in x16 organisation
(Microchip DS20001749K, Table 1-3): READ 0x80 | address, EWDS 0x00, EWEN
0x30. That reading is an inference from the values the engine writes. On
the CGL126 register map 0x8a to 0x8f are also the exposure fields EXPR and
EXPG, see the document.

Clocking risk and staged runs: how the ASIC shifts the 0x8b byte out is not
known. If it adds the start bit and sends the byte MSB first (the reading
above), every READ byte is a READ. Under other clockings some READ bytes
form other commands, EWEN included: raw MSB first with bit 7 as the start
bit makes words 0x18 to 0x1f EWEN, 0x20 to 0x3f WRITE and 0x10 to 0x17
ERAL. Start bit plus LSB first makes words 0x0c, 0x1c, 0x2c and 0x3c EWEN.
A 64-word sweep can then enable writes and erase or overwrite the chip.
Words 0 to 7 (0x80 to 0x87) and EWDS (0x00) form no EWEN under any of the
four clockings in the document, provided the data line stays at one level
after the byte, so the default run reads only those
(--words 8). Under two of the clockings some of them form WRITE, ERASE or
ERAL. Those take no effect while the chip is write-disabled, which rests
on two assumptions: the chip powers up write-disabled (DS20001749K, section
2.6) and has been powered off since any earlier traffic to 0x8b (unplug
the 24 V adapter once before the first run: a wake from standby may not
remove power from the EEPROM), and no
byte of the run forms EWEN, which holds for the four clockings considered.
Read more words (--words 64) only after the first run has shown that the
clocking is the expected one, see the document.

Safety, checked before every transfer (check_register_write,
check_register_read):
- The only register writes are 0x0a with nothing but the EPROMSEL bit
  (bit 3) changed from the value read, and 0x8b with READ (0x80 to 0xbf) or
  EWDS (0x00). EWEN (0x30), WRITE (0x40 | a), ERASE (0xc0 | a), ERAL (0x20)
  and WRAL (0x10) are refused. Whether a refused opcode could still be
  formed on the wire depends on the clocking, see above.
- The only register reads are 0x0a, the busy register 0x4f, the data
  registers 0x8f and 0x8e, and 0x31 and 0x34 for the log.
- Every write of 0x0a is read back. A read of 0x31 returns pin levels, not
  the latch, so a read of 0x0a might too. On a mismatch the run stops.
- 0x0a is put back to the value read at the end, also after an error (best
  effort, read back as well).
- Every busy wait polls at most BUSY_POLL_LIMIT times.

Before a run: unplug the scanner's 24 V adapter once and plug it back in
(see above). On the Pi: create ~/plustek-preservation/probe-disabled, and
make sure keep_awake.py does not run on this wake (it writes 0x31 and 0x34,
and 0x34 should keep its power-on value): in the current watch-scanner.sh
that means ~/plustek-preservation/keep-awake-enabled must not exist. Start
the run after the watcher has logged "probe disabled" (or "keep awake exit")
for this connection. The tool refuses to start while the file is missing or
a probe_readonly.py or keep_awake.py process runs.

Sequence:
1. Read 0x31, 0x34, 0x4f, 0x8e and 0x8f and log them.
2. Read 0x0a, set EPROMSEL if it is clear (the OpticFilm 120's plist base
   table already sets it) and read it back, then wait until 0x4f bit 4 is
   clear.
3. Two passes over words 0 to N - 1, ascending, then descending. Per word,
   in the vendor's order: write READ to 0x8b, read 0x8f (low byte), wait,
   read 0x8e (high byte), wait. The vendor waits only after the first data
   read. A read that comes too early shows up as differing passes.
4. Write EWDS to 0x8b, wait, put 0x0a back.
5. Compare the passes, log whether the data registers follow the address,
   check for a uniform image, search for the identity.

The image is the N words as 16-bit little-endian, the layout ReadFromNVRAM
leaves in memory on x86_64. Every run writes to a new timestamped directory
under OUTPUT_DIRECTORY: pass1.bin, pass2.bin (both in address order, each
word written as it arrives) and log.jsonl.

Exit codes (1 and 2 are left to Python and argparse): 0 good read (passes
agree, words not all equal), 10 no scanner with bcdDevice 0x0702 found, 11
busy timeout, 12 passes differ, 13 USB error, short transfer, missing 0x55
or refused request, 14 0x0a read back differs from the value written, 15
every word equal (all ffff means no chip fitted, a blank chip or a data
line stuck high, all 0000 a data line stuck low, any other value that the
data registers do not follow the address), 16 probe-disabled missing or a
conflicting process running.

Usage (on the Pi):
    sudo ~/plustek-preservation/venv/bin/python eeprom_read.py OUTPUT_DIRECTORY [--words N]
"""

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import struct
import sys
import time
import typing

import usb.core

KNOWN_IDENTITIES = ((0x05E3, 0x0103), (0x07B3, 0x1406))
REQUIRED_BCD_DEVICE = 0x0702  # CGL126, the only class with EPROMSEL at 0x0a bit 3 for this scanner
TIMEOUT_MILLISECONDS = 1000
REQUEST = 0x04
REGISTER_WRITE_VALUE = 0x0083
REGISTER_READ_VALUE = 0x008E
REGISTER_READ_INDEX_BASE = 0x22
READ_ACKNOWLEDGE = 0x55

EPROMSEL_REGISTER = 0x0A
EPROMSEL_BIT = 0x08
COMMAND_REGISTER = 0x8B
DATA_LOW_REGISTER = 0x8F
DATA_HIGH_REGISTER = 0x8E
BUSY_REGISTER = 0x4F
BUSY_BIT = 0x10
LOGGED_REGISTERS = (0x31, 0x34)
ALLOWED_READS = frozenset({EPROMSEL_REGISTER, BUSY_REGISTER, DATA_LOW_REGISTER, DATA_HIGH_REGISTER,
                           *LOGGED_REGISTERS})

DEFAULT_WORD_COUNT = 8  # words 0 to 7 form no EWEN under any clocking considered
MIN_WORD_COUNT = 2
MAX_WORD_COUNT = 64
ADDRESS_MASK = 0x3F
READ_OPCODE = 0x80
EWDS_COMMAND = 0x00

BUSY_POLL_INTERVAL_SECONDS = 0.1  # CAsic::CheckBusy sleeps 100 ms before every poll
BUSY_POLL_LIMIT = 20

VID_PID_LITTLE_ENDIAN = bytes.fromhex("b3070614")
FILM_SCANNER_UTF16LE = "Film Scanner".encode("utf-16-le")
CONFLICTING_SCRIPT_NAMES = (b"probe_readonly.py", b"keep_awake.py")

EXIT_GOOD = 0
EXIT_NOT_FOUND = 10
EXIT_BUSY_TIMEOUT = 11
EXIT_PASSES_DIFFER = 12
EXIT_USB_ERROR = 13
EXIT_READBACK = 14
EXIT_UNIFORM = 15
EXIT_PROBE_ACTIVE = 16


@dataclasses.dataclass
class Session:
    device: typing.Any
    log_file: typing.TextIO
    sleep: typing.Callable[[float], None] = time.sleep
    original_0a: typing.Optional[int] = None
    current_0a: typing.Optional[int] = None


class ShortTransferError(Exception):
    pass


class ProtocolError(Exception):
    pass


class BusyTimeoutError(Exception):
    pass


class ReadbackError(Exception):
    pass


def utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def log(session: Session, record: dict) -> None:
    line = json.dumps({"time": utc_timestamp(), **record})
    session.log_file.write(line + "\n")
    session.log_file.flush()
    print(line, flush=True)


def command_allowed(value: int) -> bool:
    """READ (0x80 | address 0 to 63) or EWDS (0x00), nothing else."""
    return value == EWDS_COMMAND or READ_OPCODE <= value <= READ_OPCODE | ADDRESS_MASK


def check_register_write(session: Session, register: int, value: int) -> None:
    """Raise unless the write is a READ or EWDS command, or toggles only EPROMSEL."""
    if not 0 <= value <= 0xFF:
        raise PermissionError(f"value {value} out of range")
    if register == COMMAND_REGISTER:
        if not command_allowed(value):
            raise PermissionError(f"refusing command 0x{value:02x} to register 0x8b")
        return
    if register != EPROMSEL_REGISTER:
        raise PermissionError(f"refusing write to register 0x{register:02x}")
    if session.original_0a is None:
        raise PermissionError("refusing write to 0x0a before it was read")
    if (value ^ session.original_0a) & ~EPROMSEL_BIT or (value ^ session.current_0a) != EPROMSEL_BIT:
        raise PermissionError(f"0x0a = 0x{value:02x} changes more than EPROMSEL "
                              f"(read 0x{session.original_0a:02x}, now 0x{session.current_0a:02x})")


def check_register_read(register: int) -> None:
    if register not in ALLOWED_READS:
        raise PermissionError(f"refusing read of register 0x{register:02x}")


def check_word_count(word_count: int) -> None:
    if not MIN_WORD_COUNT <= word_count <= MAX_WORD_COUNT:
        raise PermissionError(f"word count {word_count} outside {MIN_WORD_COUNT} to {MAX_WORD_COUNT}")


def read_register(session: Session, register: int) -> int:
    check_register_read(register)
    index = REGISTER_READ_INDEX_BASE + (register << 8)
    reply = bytes(session.device.ctrl_transfer(0xC0, REQUEST, REGISTER_READ_VALUE, index, 2, TIMEOUT_MILLISECONDS))
    if len(reply) != 2:
        raise ShortTransferError(f"read of register 0x{register:02x}: got {len(reply)} of 2 bytes")
    if reply[1] != READ_ACKNOWLEDGE:
        raise ProtocolError(f"read of register 0x{register:02x}: answer {reply.hex(' ')}, no 0x55")
    return reply[0]


def write_register(session: Session, register: int, value: int) -> None:
    check_register_write(session, register, value)
    if register == EPROMSEL_REGISTER:
        session.current_0a = value  # before the transfer: a failed write may still have reached the chip
    written = session.device.ctrl_transfer(0x40, REQUEST, REGISTER_WRITE_VALUE, 0, bytes([register, value]),
                                           TIMEOUT_MILLISECONDS)
    if written != 2:
        raise ShortTransferError(f"write of register 0x{register:02x}: sent {written} of 2 bytes")


def write_epromsel_register(session: Session, value: int) -> None:
    """Write 0x0a and read it back: a read that does not return the latch must stop the run."""
    write_register(session, EPROMSEL_REGISTER, value)
    read_back = read_register(session, EPROMSEL_REGISTER)
    if read_back != value:
        raise ReadbackError(f"0x0a written 0x{value:02x}, read back 0x{read_back:02x}")


def wait_not_busy(session: Session) -> int:
    """Poll 0x4f until bit 4 is clear, as CAsic::CheckBusy but bounded. Return the number of polls."""
    for poll in range(1, BUSY_POLL_LIMIT + 1):
        session.sleep(BUSY_POLL_INTERVAL_SECONDS)
        if not read_register(session, BUSY_REGISTER) & BUSY_BIT:
            return poll
    raise BusyTimeoutError(f"0x4f bit 4 still set after {BUSY_POLL_LIMIT} polls")


def read_word(session: Session, address: int) -> int:
    """One word in the order of CAsic::ReadFromNVRAM: command, low byte, wait, high byte, wait."""
    if not 0 <= address <= ADDRESS_MASK:
        raise PermissionError(f"address {address} outside the 93C46 x16 range")
    write_register(session, COMMAND_REGISTER, READ_OPCODE | address)
    low = read_register(session, DATA_LOW_REGISTER)
    wait_not_busy(session)
    high = read_register(session, DATA_HIGH_REGISTER)
    wait_not_busy(session)
    return low | high << 8


def read_pass(session: Session, addresses: list, pass_file) -> dict:
    words = {}
    for address in addresses:
        words[address] = read_word(session, address)
        pass_file.seek(2 * address)
        pass_file.write(struct.pack("<H", words[address]))
        pass_file.flush()
    return words


def assemble(words: dict, word_count: int) -> bytes:
    return b"".join(struct.pack("<H", words[address]) for address in range(word_count))


def select_eeprom(session: Session) -> None:
    session.original_0a = session.current_0a = read_register(session, EPROMSEL_REGISTER)
    log(session, {"kind": "epromsel", "action": "read", "0x0a": f"{session.original_0a:02x}"})
    if session.original_0a & EPROMSEL_BIT:
        log(session, {"kind": "epromsel", "action": "already set, not written"})
        return
    write_epromsel_register(session, session.original_0a | EPROMSEL_BIT)
    log(session, {"kind": "epromsel", "action": "set", "0x0a": f"{session.current_0a:02x}"})


def restore_epromsel(session: Session) -> None:
    """Put 0x0a back to the value read, best effort: errors are logged, not raised."""
    if session.original_0a is None or session.current_0a == session.original_0a:
        return
    try:
        write_epromsel_register(session, session.original_0a)
        log(session, {"kind": "epromsel", "action": "restored", "0x0a": f"{session.original_0a:02x}"})
    except (usb.core.USBError, ShortTransferError, PermissionError, ProtocolError, ReadbackError) as error:
        log(session, {"kind": "epromsel", "action": "restore failed", "error": str(error)})


def read_both_passes(session: Session, run_directory: pathlib.Path, word_count: int) -> list:
    """Every USB transfer of a run. 0x0a is put back however this ends."""
    check_word_count(word_count)
    try:
        before = {f"0x{register:02x}": f"{read_register(session, register):02x}"
                  for register in (*LOGGED_REGISTERS, BUSY_REGISTER, DATA_HIGH_REGISTER, DATA_LOW_REGISTER)}
        log(session, {"kind": "registers_before", **before})
        select_eeprom(session)
        wait_not_busy(session)
        ascending = list(range(word_count))
        images = []
        for pass_number, addresses in ((1, ascending), (2, ascending[::-1])):
            with open(run_directory / f"pass{pass_number}.bin", "wb") as pass_file:
                image = assemble(read_pass(session, addresses, pass_file), word_count)
            log(session, {"kind": "pass_done", "pass": pass_number, "sha256": hashlib.sha256(image).hexdigest()})
            images.append(image)
        write_register(session, COMMAND_REGISTER, EWDS_COMMAND)
        wait_not_busy(session)
        return images
    finally:
        restore_epromsel(session)


def differing_words(first: bytes, second: bytes) -> list:
    return [f"{offset // 2:02x}" for offset in range(0, len(first), 2)
            if first[offset:offset + 2] != second[offset:offset + 2]]


def words_of(image: bytes) -> tuple:
    return struct.unpack(f"<{len(image) // 2}H", image)


def address_dependence(image: bytes) -> dict:
    """How many different values 0x8f and 0x8e gave across the addresses."""
    words = words_of(image)
    record = {"words": len(words), "distinct_low_0x8f": len({word & 0xFF for word in words}),
              "distinct_high_0x8e": len({word >> 8 for word in words}), "follows_address": len(set(words)) > 1}
    if not record["follows_address"]:
        record["note"] = ("all words equal: 0x8f and 0x8e do not follow the address. Other than ffff this fits "
                          "0x8e and 0x8f being the EXPG exposure bytes, not an EEPROM interface")
    return record


def uniform_word(image: bytes) -> typing.Optional[int]:
    """The word value when all words are equal, else None."""
    words = set(words_of(image))
    return words.pop() if len(words) == 1 else None


def byte_swapped(image: bytes) -> bytes:
    return bytes(image[offset ^ 1] for offset in range(len(image)))


def identity_search(image: bytes) -> dict:
    """Look for 07b3:1406 and "Film Scanner" as laid out, and with the two bytes of each word swapped."""
    swapped = byte_swapped(image)
    return {"vid_pid_le": VID_PID_LITTLE_ENDIAN in image, "film_scanner_utf16le": FILM_SCANNER_UTF16LE in image,
            "vid_pid_le_bytes_swapped": VID_PID_LITTLE_ENDIAN in swapped,
            "film_scanner_utf16le_bytes_swapped": FILM_SCANNER_UTF16LE in swapped}


def hex_dump(image: bytes) -> list:
    return [f"{offset:02x}: {image[offset:offset + 16].hex(' ')}" for offset in range(0, len(image), 16)]


def evaluate(session: Session, images: list) -> int:
    mismatches = differing_words(images[0], images[1])
    log(session, {"kind": "compare", "differing_words": mismatches})
    log(session, {"kind": "hex_dump", "pass": 1, "lines": hex_dump(images[0])})
    if mismatches:
        log(session, {"kind": "hex_dump", "pass": 2, "lines": hex_dump(images[1])})
        return EXIT_PASSES_DIFFER
    log(session, {"kind": "address_dependence", **address_dependence(images[0])})
    value = uniform_word(images[0])
    if value is not None:
        log(session, {"kind": "uniform_image", "word": f"{value:04x}",
                      "note": "ffff: no chip, blank chip or data stuck high. 0000: data stuck low. "
                              "Other: the data registers do not follow the address."})
        return EXIT_UNIFORM
    log(session, {"kind": "identity_search", **identity_search(images[0])})
    return EXIT_GOOD


def run(session: Session, run_directory: pathlib.Path, word_count: int = DEFAULT_WORD_COUNT) -> int:
    """read_both_passes() and evaluate(), with errors logged and mapped to an exit code."""
    try:
        exit_code = evaluate(session, read_both_passes(session, run_directory, word_count))
    except BusyTimeoutError as error:
        log(session, {"kind": "error", "error": str(error)})
        exit_code = EXIT_BUSY_TIMEOUT
    except ReadbackError as error:
        log(session, {"kind": "error", "error": str(error)})
        exit_code = EXIT_READBACK
    except (usb.core.USBError, PermissionError, ShortTransferError, ProtocolError) as error:
        log(session, {"kind": "error", "error": str(error)})
        exit_code = EXIT_USB_ERROR
    log(session, {"kind": "exit", "code": exit_code})
    return exit_code


def conflicting_process_running(proc_root: pathlib.Path) -> bool:
    """True when any process has probe_readonly.py or keep_awake.py among its arguments."""
    for cmdline in proc_root.glob("[0-9]*/cmdline"):
        try:
            arguments = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        if any(argument.endswith(CONFLICTING_SCRIPT_NAMES) for argument in arguments):
            return True
    return False


def word_count_argument(text: str) -> int:
    try:
        word_count = int(text, 0)
        check_word_count(word_count)
    except (ValueError, PermissionError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return word_count


def find_scanner():
    for vendor_id, product_id in KNOWN_IDENTITIES:
        device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if device is not None and device.bcdDevice == REQUIRED_BCD_DEVICE:
            return device
    return None


def new_run_directory(output_directory: pathlib.Path) -> pathlib.Path:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_directory = output_directory / stamp
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Read the scanner's serial EEPROM through ASIC registers.")
    parser.add_argument("output_directory", type=pathlib.Path)
    parser.add_argument("--words", type=word_count_argument, default=DEFAULT_WORD_COUNT,
                        help=f"number of words to read from address 0 (default {DEFAULT_WORD_COUNT}, at most "
                             f"{MAX_WORD_COUNT}). More than 8 only once the clocking is known, see the docstring.")
    arguments = parser.parse_args()
    probe_disabled = pathlib.Path(__file__).resolve().parent / "probe-disabled"
    if not probe_disabled.exists() or conflicting_process_running(pathlib.Path("/proc")):
        print(f"create {probe_disabled} and wait until no probe_readonly.py or keep_awake.py process runs",
              file=sys.stderr)
        return EXIT_PROBE_ACTIVE
    device = find_scanner()
    if device is None:
        print(f"no scanner with bcdDevice 0x{REQUIRED_BCD_DEVICE:04x} found", file=sys.stderr)
        return EXIT_NOT_FOUND
    run_directory = new_run_directory(arguments.output_directory)
    print(f"output in {run_directory}", flush=True)
    with open(run_directory / "log.jsonl", "w") as log_file:
        session = Session(device, log_file)
        log(session, {"kind": "device", "vendor_id": f"{device.idVendor:04x}",
                      "product_id": f"{device.idProduct:04x}", "bcd_device": f"{device.bcdDevice:04x}",
                      "words": arguments.words})
        return run(session, run_directory, arguments.words)


if __name__ == "__main__":
    sys.exit(main())
