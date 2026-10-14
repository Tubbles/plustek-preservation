"""Replay the vendor driver's open sequence on the OpticFilm 120, then watch the bus.

Sends, byte for byte and in the same order, the requests Plustek's Windows
driver sent to a working OpticFilm 120 at device open in the issue #151
capture, frames 15 to 138 (doc/protocol/of120-capture-151.md, "Open" and
"The register blast"). Two purposes: the standby experiment, and the
scanner state a later motor move starts from
(doc/work/0011-first-motor-move.md). The unit leaves the bus about 5
minutes after a wake, and driving GPIO8 alone does not hold it
(doc/hardware/usb.md, "Standby"). The open adds a 13 ms low pulse on
GPIO8 and other GPIO writes.

What it sends, from the table OPEN_SEQUENCE (one record per capture
request, with the bytes sent and the answer the working unit gave):
the one-byte read at wValue 0x8a wIndex 0x26fe; the register blast in four
transfers of 32, 32, 32 and 20 address-value pairs; 0x114 = 0x80 and
0x115 = 0x80 through wValue 0x183; the system and AHB clocks (wValue 0x8c,
index 0x10 and 0x13, both 0x0d); 0x0b = 0x64, 0x13 = 0x0f, 0x0b = 0x6c;
SPI init, the flash ID read, the address write for flash address 0 and one
64-byte flash read (read-only, the requests flash_dump.py sends); two
reads of 0x101; 0x03 = 0x00 (lamp); the eight AFE writes; read 0x36,
0x36 = 0xfe; read 0x33, 0x33 = 0x0e; the one-byte read at wIndex 0; read
0x31, 0x31 = 0x3e, read 0x31, 0x31 = 0xbe. After every write it sends the
link check (c0 0c 008e wIndex 0x20, 1 byte), as the capture does, and
requires 0x55. The values written are the capture's constants, not
read-modify-write: the reads of 0x36, 0x33 and 0x31 return pin levels,
which differ between units. Every read is logged next to the answer of
the working unit, with a "differs" flag. A difference does not stop the
run.

Timing: the capture's pauses of more than 5 ms between requests are kept
(26.6 ms before the blast, 12.4 ms before the SPI init, 68.3 ms before the
0x101 reads, 12.3 ms between the link check of 0x31 = 0x3e and the read of
0x31 that follows). The last one makes the low pulse on 0x31 bit 7 about
13 ms long, as in the capture (13.3 ms from write to write).

Motor: the blast writes 0x02 = 0x78 (ACDCDIS, AGOHOME, MTRPWR, FASTFED,
with ACDCDIS as bit 6 in SANE's backend/genesys/gl124_registers.h line
45), as the vendor does at every open, and no start (0x0f). SANE's GL124
backend sets AGOHOME as a flag of a scan it then starts
(work/downloads/sane-project/sane-backends-git/backend/genesys/gl124.cpp,
commit a8676a6, lines 494 to 496, started at line 889 with
scanner_start_action), and the capture's ten carrier moves and two image
scans each follow a start write (0x0f = 0x01, 40 in the capture,
doc/protocol/of120-moves.md, "Overview"). So no motion is expected from
the blast. The working unit did not move after it: 0x101 read 0xdc in
frames 73 and 75 (MOTORENB clear, doc/protocol/of120-moves.md, "Status
values"). But that unit's carrier was at home (HOMESNR, bit 3, is set in
0xdc too), so the capture does not show the blast with a carrier away
from home. Hence the home gate in step 2. doc/hardware/board.md,
"Reassembly", holds back requests that power the motor until
doc/work/0010-mechanical-check.md is done, and MTRPWR in the blast is
such a request.

Sequence:
1. Read 0x101, 0x31, 0x34, 0x36, 0x33, 0x0a, 0x02 and 0x06 and log them.
   0x02 is the only one neither the capture nor an earlier tool reads.
   pyopticfilm reads it on the 8200i SE's GL128 with the same framing
   (pyopticfilm/src/pyopticfilm/asic/gl128.py line 385).
2. Home gate: unless 0x101 has HOMESNR (bit 3) set and MOTORENB (bit 0)
   clear, as on the working unit, log a "refused" record and exit 21
   before any OUT transfer. --carrier-off-home-ok skips the gate, for the
   owner to decide after seeing the value.
3. Replay OPEN_SEQUENCE.
4. Watch: right after the open and then every 20 s until --watch-seconds
   have passed, find the scanner again, send the link check and read
   0x101, and log both. Here the link byte is only logged: every link
   check in the capture comes within 1 ms of a write, and the owner's
   unit answers 0xaa to one with no write before it
   (doc/hardware/usb.md, "Read-only probe"). The 0x101 read still needs
   0x55 as its second byte. When the scanner is gone (USB error "No such
   device", or no scanner at the same bus and address), log the seconds
   since the end of the open and stop. After any other USB error the tool
   waits 2 s and looks for the scanner once more: gone counts as the
   drop, still there is exit 13. No transfer is retried. The resolution
   is the poll interval. watch-scanner.sh logs the time the unit left to
   the second.

Safety, checked before every transfer (check_allowed): a replayed request
must be one of OPEN_SEQUENCE, unchanged. A register write of 0x0f (motor
start) and the flash program and erase requests are refused even then.
Apart from the table, the tool sends only register reads of the eight
registers above and the link check. It has no bulk transfer.

Before a run: create ~/plustek-preservation/probe-disabled next to this
script so that watch-scanner.sh does not start the probe on the wake, and
make sure keep_awake.py does not run
(~/plustek-preservation/keep-awake-enabled must not exist). The film
holder stays out of the unit (doc/hardware/board.md, "Reassembly") and
the owner stays at the power switch. Start the run after the watcher has
logged "probe disabled" for this connection, so that its lsusb run is
over, but soon after the wake, and keep the watcher's "connected" stamp:
the tool measures the drop from the end of the open, while the known
interval is 4 min 55 s from the wake (doc/hardware/usb.md, "Standby").
The tool refuses to start while the file is missing or a
probe_readonly.py or keep_awake.py process runs. Each run needs the
owner's go-ahead.

Every run writes LOG_DIRECTORY/<UTC stamp>/log.jsonl: one line per
request (kind, the capture frame it replays, setup fields, bytes sent,
bytes received, the captured answer), one per watch poll.

Exit codes (1 and 2 are left to Python and argparse): 0 the watch ended
with the scanner still present, 10 scanner not found, 13 USB error, short
transfer, link byte other than 0x55 (in the watch only the 0x101 read's)
or refused request (the log names the frame the open reached), 16
probe-disabled missing or probe_readonly.py or keep_awake.py running, 19
bcdDevice other than 0x0702, 20 the scanner left the bus during the
watch, 21 the home gate refused the run (no OUT transfer sent).

Usage (on the Pi):
    sudo ~/plustek-preservation/venv/bin/python vendor_open.py LOG_DIRECTORY [--watch-seconds N]
        [--carrier-off-home-ok]
"""

import argparse
import dataclasses
import errno
import pathlib
import sys
import time
import typing

import usb.core

from eeprom_read import conflicting_process_running
from flash_dump import (BLOCK_SIZE, EXIT_NOT_FOUND, EXIT_PROBE_ACTIVE, EXIT_USB_ERROR, FLASH_WRITE_VALUE,
                        TIMEOUT_MILLISECONDS, Session, ShortTransferError, check_write_allowed, control_in,
                        find_scanner, link_check, log, new_run_directory)
from keep_awake import EXIT_WRONG_CHIP, GL128_BCD_DEVICE, LinkByteError

VENDOR_OUT = 0x40
VENDOR_IN = 0xC0
REGISTER_WRITE_VALUE = 0x0083
LINK_BYTE = 0x55
STATUS_REGISTER = 0x101
HOMESNR_BIT = 0x08
MOTORENB_BIT = 0x01
LOGGED_REGISTERS = (STATUS_REGISTER, 0x31, 0x34, 0x36, 0x33, 0x0A, 0x02, 0x06)
MOTOR_START_REGISTER = 0x0F
FLASH_READ_LIMIT = BLOCK_SIZE  # the open reads only the block at flash address 0
POLL_INTERVAL_SECONDS = 20
REFIND_DELAY_SECONDS = 2
DEFAULT_WATCH_SECONDS = 420

EXIT_GOOD = 0
EXIT_DROPPED = 20
EXIT_CARRIER_NOT_HOME = 21


@dataclasses.dataclass(frozen=True)
class CapturedRequest:
    """One request of the capture: setup fields, the bytes sent, the answer the working unit gave."""
    frame: int
    kind: str
    request_type: int
    request: int
    value: int
    index: int
    sent: bytes
    answer: bytes
    link_check_after: bool
    pause_before_milliseconds: float = 0.0


@dataclasses.dataclass
class Environment:
    """What a run needs besides the USB device, replaceable in tests."""
    sleep: typing.Callable[[float], None] = time.sleep
    monotonic: typing.Callable[[], float] = time.monotonic
    find_device: typing.Callable[[], typing.Any] = find_scanner


class StoppedAtFrame(Exception):
    def __init__(self, frame: int):
        super().__init__(f"stopped at capture frame {frame}")
        self.frame = frame


def write_request(frame: int, kind: str, request: int, value: int, index: int, sent_hex: str,
                  pause_before_milliseconds: float = 0.0) -> CapturedRequest:
    """An OUT request. Every one in frames 15 to 138 is followed by a link check."""
    return CapturedRequest(frame, kind, VENDOR_OUT, request, value, index, bytes.fromhex(sent_hex), b"", True,
                           pause_before_milliseconds)


def read_request(frame: int, kind: str, request: int, value: int, index: int, answer_hex: str,
                 pause_before_milliseconds: float = 0.0) -> CapturedRequest:
    return CapturedRequest(frame, kind, VENDOR_IN, request, value, index, b"", bytes.fromhex(answer_hex), False,
                           pause_before_milliseconds)


# Frames 15 to 138 of the issue #151 capture, link checks left out (link_check_after marks them).
# Register writes are address and value pairs; test_vendor_open.py checks this table against the capture.
OPEN_SEQUENCE = (
    read_request(15, "vendor_read", 0x0C, 0x008A, 0x26FE, "00"),
    write_request(17, "register_write", 0x04, 0x0083, 0x0000,
                  "0122 0278 0320 0402 05c8 0618 0700 0880 0900 0a48 0b6c 0c00 0d00 1100 1204 1308"
                  " 1401 1580 1601 170c 1814 1900 1a00 1b00 1c00 1d00 1e10 1f00 200c 2100 221a 2300",
                  pause_before_milliseconds=26.6),
    write_request(21, "register_write", 0x04, 0x0083, 0x0000,
                  "241a 2500 2600 2700 2b20 2c12 2dc0 306f 31fc 326b 330e 3480 357f 36fc 3730 3877"
                  " 3902 3a00 3bff 3cff 3d00 3e00 3f01 4f03 5207 5309 540b 5501 5603 5705 5a12 5b00"),
    write_request(25, "register_write", 0x04, 0x0083, 0x0000,
                  "5c00 5e1f 5f01 6000 6100 6320 677f 687f 6901 7006 7109 7208 7309 7400 7500 7600"
                  " 7700 7800 7900 7a00 7b00 7c00 7d00 7e75 7f30 8000 8122 8200 8301 8418 8500 8600"),
    write_request(29, "register_write", 0x04, 0x0083, 0x0000,
                  "8700 9300 9400 9500 9d08 a012 a400 a520 a600 a780 a800 a980 aa00 ab30 b800 b938"
                  " ba00 bd00 be00 bf00"),
    write_request(33, "register_write", 0x04, 0x0183, 0x0000, "1480 1580"),
    write_request(37, "usb_register_write", 0x0C, 0x008C, 0x0010, "0d"),
    write_request(41, "usb_register_write", 0x0C, 0x008C, 0x0013, "0d"),
    write_request(45, "register_write", 0x04, 0x0083, 0x0000, "0b64"),
    write_request(49, "register_write", 0x04, 0x0083, 0x0000, "130f"),
    write_request(53, "register_write", 0x04, 0x0083, 0x0000, "0b6c"),
    write_request(57, "flash_write", 0x0C, 0x008B, 0x0007, "01", pause_before_milliseconds=12.4),
    write_request(61, "flash_write", 0x04, 0x008B, 0x0009, "00000000"),
    read_request(65, "flash_read", 0x04, 0x008A, 0x0010, "c22013"),
    write_request(67, "flash_write", 0x04, 0x008B, 0x000B, "00000000"),
    read_request(71, "flash_read", 0x04, 0x008A, 0x000F,
                 "b4140000 1d020000 ff280000 44020000 4a020000 dd280000 58020000 ffffffff"
                 " ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff"),
    read_request(73, "register_read", 0x04, 0x018E, 0x0122, "dc55", pause_before_milliseconds=68.3),
    read_request(75, "register_read", 0x04, 0x018E, 0x0122, "dc55"),
    write_request(77, "register_write", 0x04, 0x0083, 0x0000, "0300"),
    write_request(81, "register_write", 0x04, 0x0083, 0x0000, "5100 5d00 5ef8"),
    write_request(85, "register_write", 0x04, 0x0083, 0x0000, "5101 5d00 5e80"),
    write_request(89, "register_write", 0x04, 0x0083, 0x0000, "5102 5d00 5e00"),
    write_request(93, "register_write", 0x04, 0x0083, 0x0000, "5103 5d00 5e00"),
    write_request(97, "register_write", 0x04, 0x0083, 0x0000, "5104 5d00 5e00"),
    write_request(101, "register_write", 0x04, 0x0083, 0x0000, "5105 5d00 5e00"),
    write_request(105, "register_write", 0x04, 0x0083, 0x0000, "5106 5d00 5e00"),
    write_request(109, "register_write", 0x04, 0x0083, 0x0000, "5107 5d00 5e00"),
    read_request(113, "register_read", 0x04, 0x008E, 0x3622, "fc55"),
    write_request(115, "register_write", 0x04, 0x0083, 0x0000, "36fe"),
    read_request(119, "register_read", 0x04, 0x008E, 0x3322, "0e55"),
    write_request(121, "register_write", 0x04, 0x0083, 0x0000, "330e"),
    read_request(125, "vendor_read", 0x0C, 0x008E, 0x0000, "00"),
    read_request(127, "register_read", 0x04, 0x008E, 0x3122, "be55"),
    write_request(129, "register_write", 0x04, 0x0083, 0x0000, "313e"),
    read_request(133, "register_read", 0x04, 0x008E, 0x3122, "3e55", pause_before_milliseconds=12.3),
    write_request(135, "register_write", 0x04, 0x0083, 0x0000, "31be"),
)

REQUEST_ERRORS = (usb.core.USBError, PermissionError, ShortTransferError, LinkByteError)


def written_registers(record: CapturedRequest) -> bytes:
    """The register addresses a wValue 0x0083 write sets (its payload is address and value pairs)."""
    if record.request_type != VENDOR_OUT or record.value != REGISTER_WRITE_VALUE:
        return b""
    return record.sent[0::2]


def check_allowed(record: CapturedRequest) -> None:
    """Raise unless the record is one of OPEN_SEQUENCE, unchanged. A motor start or flash program is refused anyway."""
    if MOTOR_START_REGISTER in written_registers(record):
        raise PermissionError(f"frame {record.frame}: refusing a write of register 0x0f")
    if record.request_type == VENDOR_OUT and record.value == FLASH_WRITE_VALUE:
        check_write_allowed(record.index, record.sent, FLASH_READ_LIMIT)
    if record not in OPEN_SEQUENCE:
        raise PermissionError(f"frame {record.frame}: not a request of the capture's open sequence")


def transfer(session: Session, record: CapturedRequest) -> bytes:
    """The record's control transfer, exactly as captured. Return the answer of a read, b"" for a write."""
    check_allowed(record)
    if record.request_type == VENDOR_IN:
        return control_in(session, record.request, record.value, record.index, len(record.answer))
    written = session.device.ctrl_transfer(VENDOR_OUT, record.request, record.value, record.index, record.sent,
                                           TIMEOUT_MILLISECONDS)
    if written != len(record.sent):
        raise ShortTransferError(f"frame {record.frame}: sent {written} of {len(record.sent)} bytes")
    return b""


def request_log_record(record: CapturedRequest, received: bytes) -> dict:
    entry = {"kind": record.kind, "frame": record.frame, "request_type": f"{record.request_type:02x}",
             "request": f"{record.request:02x}", "value": f"{record.value:04x}", "index": f"{record.index:04x}"}
    if record.request_type == VENDOR_OUT:
        return {**entry, "sent": record.sent.hex(" ")}
    return {**entry, "received": received.hex(" "), "captured": record.answer.hex(" "),
            "differs": received != record.answer}


def require_link_byte(link_byte: int, context: str) -> None:
    if link_byte != LINK_BYTE:
        raise LinkByteError(f"{context}: link byte 0x{link_byte:02x}, expected 0x55")


def send_link_check(session: Session, after_frame: int) -> None:
    received = link_check(session)
    log(session, {"kind": "link_check", "after_frame": after_frame, "received": received})
    require_link_byte(int(received, 16), f"link check after frame {after_frame}")


def replay_request(session: Session, record: CapturedRequest) -> None:
    """Send one record, log it, then check its link byte or send the link check that followed it."""
    received = transfer(session, record)
    log(session, request_log_record(record, received))
    if record.kind == "register_read":
        require_link_byte(received[1], f"frame {record.frame}")
    if record.link_check_after:
        send_link_check(session, record.frame)


def replay_open(session: Session, environment: Environment) -> None:
    for record in OPEN_SEQUENCE:
        if record.pause_before_milliseconds:
            environment.sleep(record.pause_before_milliseconds / 1000)
        try:
            replay_request(session, record)
        except REQUEST_ERRORS as error:
            raise StoppedAtFrame(record.frame) from error


def read_register(session: Session, register: int) -> int:
    """Register read with the capture's framing (wValue 0x018e from 0x100 up): the value, then 0x55."""
    if register not in LOGGED_REGISTERS:
        raise PermissionError(f"refusing read of register 0x{register:02x}")
    value = 0x018E if register > 0xFF else 0x008E
    answer = control_in(session, 0x04, value, 0x22 + ((register & 0xFF) << 8), 2)
    require_link_byte(answer[1], f"register 0x{register:02x}")
    return answer[0]


def read_registers_before_open(session: Session) -> dict:
    values = {register: read_register(session, register) for register in LOGGED_REGISTERS}
    log(session, {"kind": "registers_before_open",
                  **{f"0x{register:02x}": f"{value:02x}" for register, value in values.items()}})
    return values


def carrier_at_rest_at_home(status: int) -> bool:
    """0x101 with HOMESNR set and MOTORENB clear, the state the working unit was in when the blast came."""
    return bool(status & HOMESNR_BIT) and not status & MOTORENB_BIT


def same_device(device, candidate) -> bool:
    return candidate is not None and (candidate.bus, candidate.address) == (device.bus, device.address)


def device_gone(error: Exception) -> bool:
    return getattr(error, "errno", None) == errno.ENODEV or "No such device" in str(error)


def poll(session: Session, environment: Environment, open_end: float) -> typing.Optional[str]:
    """One watch poll. Return why the scanner counts as gone, or None after a good read."""
    if not same_device(session.device, environment.find_device()):
        return "no scanner at this bus and address"
    try:
        link = int(link_check(session), 16)
        status = read_register(session, STATUS_REGISTER)
    except usb.core.USBError as error:
        if device_gone(error):
            return str(error)
        environment.sleep(REFIND_DELAY_SECONDS)
        if not same_device(session.device, environment.find_device()):
            return f"{error}, then no scanner at this bus and address after {REFIND_DELAY_SECONDS} s"
        raise
    log(session, {"kind": "watch", "seconds_since_open": round(environment.monotonic() - open_end, 1),
                  "link_check": f"{link:02x}", "0x101": f"{status:02x}"})
    return None


def wait_until(environment: Environment, deadline: float) -> None:
    remaining = deadline - environment.monotonic()
    if remaining > 0:
        environment.sleep(remaining)


def watch(session: Session, environment: Environment, watch_seconds: int) -> int:
    """Poll right after the open and every POLL_INTERVAL_SECONDS after it until watch_seconds have passed."""
    open_end = environment.monotonic()
    for poll_number in range(watch_seconds // POLL_INTERVAL_SECONDS + 1):
        wait_until(environment, open_end + poll_number * POLL_INTERVAL_SECONDS)
        reason = poll(session, environment, open_end)
        if reason is not None:
            log(session, {"kind": "dropped", "seconds_since_open": round(environment.monotonic() - open_end, 1),
                          "reason": reason})
            return EXIT_DROPPED
    return EXIT_GOOD


def open_and_watch(session: Session, environment: Environment, watch_seconds: int,
                   carrier_off_home_ok: bool) -> int:
    status = read_registers_before_open(session)[STATUS_REGISTER]
    if not carrier_at_rest_at_home(status):
        if not carrier_off_home_ok:
            log(session, {"kind": "refused", "0x101": f"{status:02x}",
                          "reason": "HOMESNR clear or MOTORENB set, --carrier-off-home-ok skips this check"})
            return EXIT_CARRIER_NOT_HOME
        log(session, {"kind": "home_gate_skipped", "0x101": f"{status:02x}"})
    replay_open(session, environment)
    log(session, {"kind": "open_done", "last_frame": OPEN_SEQUENCE[-1].frame})
    return watch(session, environment, watch_seconds)


def run(session: Session, environment: Environment, watch_seconds: int = DEFAULT_WATCH_SECONDS,
        carrier_off_home_ok: bool = False) -> int:
    """open_and_watch() with errors logged and mapped to an exit code."""
    try:
        exit_code = open_and_watch(session, environment, watch_seconds, carrier_off_home_ok)
    except StoppedAtFrame as stop:
        log(session, {"kind": "error", "frame": stop.frame, "error": str(stop.__cause__)})
        exit_code = EXIT_USB_ERROR
    except REQUEST_ERRORS as error:
        log(session, {"kind": "error", "error": str(error)})
        exit_code = EXIT_USB_ERROR
    log(session, {"kind": "exit", "code": exit_code})
    return exit_code


def refusal_exit_code(probe_disabled: pathlib.Path, proc_root: pathlib.Path, device) -> typing.Optional[int]:
    """The exit code that refuses the run, or None when it may start."""
    if not probe_disabled.exists() or conflicting_process_running(proc_root):
        return EXIT_PROBE_ACTIVE
    if device is None:
        return EXIT_NOT_FOUND
    if device.bcdDevice != GL128_BCD_DEVICE:
        return EXIT_WRONG_CHIP
    return None


def watch_seconds_argument(text: str) -> int:
    seconds = int(text)
    if seconds < 0:
        raise argparse.ArgumentTypeError("watch seconds must be 0 or more")
    return seconds


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay the vendor's open sequence, then watch the bus.")
    parser.add_argument("log_directory", type=pathlib.Path)
    parser.add_argument("--watch-seconds", type=watch_seconds_argument, default=DEFAULT_WATCH_SECONDS,
                        help=f"how long to watch after the open (default {DEFAULT_WATCH_SECONDS})")
    parser.add_argument("--carrier-off-home-ok", action="store_true",
                        help="replay the open even when 0x101 does not show the carrier at rest at home")
    return parser


def main() -> int:
    arguments = argument_parser().parse_args()
    probe_disabled = pathlib.Path(__file__).resolve().parent / "probe-disabled"
    device = find_scanner()
    refusal = refusal_exit_code(probe_disabled, pathlib.Path("/proc"), device)
    if refusal is not None:
        messages = {EXIT_PROBE_ACTIVE: f"create {probe_disabled} and wait until no probe_readonly.py or "
                                       "keep_awake.py process runs",
                    EXIT_NOT_FOUND: "scanner not found",
                    EXIT_WRONG_CHIP: f"bcdDevice is not 0x{GL128_BCD_DEVICE:04x}"}
        print(messages[refusal], file=sys.stderr)
        return refusal
    run_directory = new_run_directory(arguments.log_directory)
    print(f"output in {run_directory}", flush=True)
    with open(run_directory / "log.jsonl", "w") as log_file:
        session = Session(device, log_file)
        log(session, {"kind": "device", "vendor_id": f"{device.idVendor:04x}",
                      "product_id": f"{device.idProduct:04x}", "bcd_device": f"{device.bcdDevice:04x}",
                      "watch_seconds": arguments.watch_seconds,
                      "carrier_off_home_ok": arguments.carrier_off_home_ok})
        return run(session, Environment(), arguments.watch_seconds, arguments.carrier_off_home_ok)


if __name__ == "__main__":
    sys.exit(main())
