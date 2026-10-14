"""Keep the OpticFilm 120 out of standby by driving its standby line high.

The unit leaves the bus about 5 minutes after a wake (doc/hardware/usb.md,
"Standby"). Plustek's engine keeps it awake by holding register 0x31 bit 7
(GPIO8, plist StandbyReg) set, and its register blast sets 0x34 bit 7
(GPOE8, the output enable of GPIO8) as well: the capture of a working unit
writes 0x31 = 0xfc and 0x34 = 0x80 in that order (doc/protocol/of120-capture-151.md,
doc/vendor-driver/macos.md, "Standby"). The owner's unit reads 0x34 = 00,
so GPIO8 is not driven.

A read of 0x31 does not return the written value: the capture writes
0xfc and later reads 0xbe, with no write to 0x31 in between (bits 6 and
1 differ). This tool treats such reads as pin levels (inference). So it
always writes 0x31 bit 7 (keeping the other bits as read; their outputs
are disabled), then sets 0x34 bit 7, then reads 0x34 and 0x31 back.
Unless both read back with bit 7 set, it clears 0x34 bit 7 again (also
when a transfer fails after the enable) and exits 18. It writes no other
register.

Board revision: in the "-new1440" configuration of Plustek's macOS driver
(a newer OpticFilm 120 board, added 2022-11-18) GPIO8 is the film loader
sensor (LoaderReadyReg 0x31,0x80) and StandbyReg is disabled. Driving it
there would fight the sensor. Run this tool only on the original board.
The watcher runs it only when ~/plustek-preservation/keep-awake-enabled
exists.

Exit codes (1 and 2 are left to Python and argparse): 0 the output enable
and the pin read back high, 10 scanner not found, 13 USB error, short
transfer, wrong link byte or refused write (after the enable, the output
enable is cleared first), 18 the output enable or the pin did not read
back high (output enable cleared), 19 not a GL128 (bcdDevice other than
0x0702).

Usage (on the Pi):
    sudo ~/plustek-preservation/venv/bin/python keep_awake.py LOG_FILE
"""

import argparse
import sys

import usb.core

from flash_dump import (EXIT_NOT_FOUND, EXIT_USB_ERROR, TIMEOUT_MILLISECONDS, Session,
                        ShortTransferError, control_in, find_scanner, log)

GPIO8_REGISTER = 0x31
GPOE8_REGISTER = 0x34
STANDBY_BIT = 0x80
ALLOWED_REGISTERS = (GPIO8_REGISTER, GPOE8_REGISTER)
LINK_BYTE = 0x55
GL128_BCD_DEVICE = 0x0702
EXIT_NOT_CONFIRMED = 18
EXIT_WRONG_CHIP = 19


class LinkByteError(Exception):
    pass


def read_register(session: Session, register: int) -> int:
    """GL124/GL128 register read: the value, then the 0x55 link byte."""
    value, link = control_in(session, 0x04, 0x008E, 0x22 + (register << 8), 2)
    if link != LINK_BYTE:
        raise LinkByteError(f"register 0x{register:02x}: link byte 0x{link:02x}, expected 0x55")
    return value


def write_register(session: Session, register: int, value: int) -> None:
    if register not in ALLOWED_REGISTERS:
        raise PermissionError(f"refusing write to register 0x{register:02x}")
    data = bytes((register, value))
    written = session.device.ctrl_transfer(0x40, 0x04, 0x0083, 0, data, TIMEOUT_MILLISECONDS)
    if written != len(data):
        raise ShortTransferError(f"register 0x{register:02x}: sent {written} of {len(data)} bytes")
    log(session, {"kind": "write", "register": f"{register:02x}", "value": f"{value:02x}"})


def keep_awake(session: Session) -> int:
    """Level first, then the output enable; clear the enable again unless both read back high."""
    pins_before = read_register(session, GPIO8_REGISTER)
    write_register(session, GPIO8_REGISTER, pins_before | STANDBY_BIT)
    enable_before = read_register(session, GPOE8_REGISTER)
    write_register(session, GPOE8_REGISTER, enable_before | STANDBY_BIT)
    confirmed = False
    try:
        enable_after = read_register(session, GPOE8_REGISTER)
        pins_after = read_register(session, GPIO8_REGISTER)
        log(session, {"kind": "registers", "0x31_before": f"{pins_before:02x}",
                      "0x34_before": f"{enable_before:02x}", "0x34_after": f"{enable_after:02x}",
                      "0x31_after": f"{pins_after:02x}"})
        confirmed = bool(enable_after & STANDBY_BIT and pins_after & STANDBY_BIT)
    finally:
        if not confirmed:
            write_register(session, GPOE8_REGISTER, enable_before & ~STANDBY_BIT)
    return 0 if confirmed else EXIT_NOT_CONFIRMED


def run(session: Session) -> int:
    try:
        exit_code = keep_awake(session)
    except (usb.core.USBError, PermissionError, ShortTransferError, LinkByteError) as error:
        log(session, {"kind": "error", "error": str(error)})
        exit_code = EXIT_USB_ERROR
    log(session, {"kind": "exit", "code": exit_code})
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive the scanner's standby line high.")
    parser.add_argument("log_file")
    arguments = parser.parse_args()
    device = find_scanner()
    if device is None:
        print("scanner not found", file=sys.stderr)
        return EXIT_NOT_FOUND
    if device.bcdDevice != GL128_BCD_DEVICE:
        print(f"bcdDevice 0x{device.bcdDevice:04x} is not a GL128", file=sys.stderr)
        return EXIT_WRONG_CHIP
    with open(arguments.log_file, "w") as log_file:
        return run(Session(device, log_file))


if __name__ == "__main__":
    sys.exit(main())
