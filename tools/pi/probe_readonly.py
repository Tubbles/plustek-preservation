"""Read-only probe of an OpticFilm 120 (Genesys GL128) over USB.

Every vendor request is an IN request that Plustek's own driver sends,
with identical framing, in the issue #151 capture
(doc/protocol/of120-capture-151.md, safe probe sets A and B, plus the
register 0x06 read from later in that capture). Descriptors are read
with standard GET_DESCRIPTOR requests whose wLength pyusb chooses, at the
string indices this unit reports plus the working unit's index 11.
Nothing is written to the scanner. Prints one JSON object per request.

Usage (on the Pi, as root because no udev rule grants access):
    sudo ~/plustek-preservation/venv/bin/python probe_readonly.py
    sudo ~/plustek-preservation/venv/bin/python probe_readonly.py --watch 10
    sudo ~/plustek-preservation/venv/bin/python probe_readonly.py --watch 0.5 --gpio

--gpio adds registers 0x31 and 0x33 (GPIO pin levels) to the polling, for
the film holder test: on the original board the loader sensor is 0x31
bit 2 (plist LoaderReadyReg 0x31,0x04), on the "-new1440" board it is
0x31 bit 7 (doc/vendor-driver/macos.md). The bit is clear while a holder
is ready (CAsic::IsLoaderReady, 0x06b020 in the macOS engine). In the
issue #151 capture, bit 2 goes from 1 to 0 while a holder is presumably
inserted, and bit 0 changes with it.
"""

import argparse
import dataclasses
import datetime
import json
import sys
import time

import usb.core
import usb.util

KNOWN_IDENTITIES = ((0x05E3, 0x0103), (0x07B3, 0x1406))
GL128_BCD_DEVICE = 0x0702
VENDOR_IN = 0xC0
INTERRUPT_ENDPOINT = 0x83
TIMEOUT_MILLISECONDS = 1000


@dataclasses.dataclass(frozen=True)
class VendorRead:
    name: str
    request: int
    value: int
    index: int
    length: int


def register_read(register: int) -> VendorRead:
    """GL124/GL128 register read framing (SANE scanner_interface_usb.cpp)."""
    value = 0x018E if register > 0xFF else 0x008E
    index = 0x22 + ((register & 0xFF) << 8)
    return VendorRead(f"register 0x{register:03x}", 0x04, value, index, 2)


def one_byte_read(name: str, value: int, index: int) -> VendorRead:
    return VendorRead(name, 0x0C, value, index, 1)


LINK_CHECK = one_byte_read("link check", 0x008E, 0x0020)
STATUS_REGISTER = register_read(0x101)
GPIO_READS = (register_read(0x31), register_read(0x33))

# Every entry is a read the vendor driver sends in the issue #151 capture.
VENDOR_READS = (
    one_byte_read("first open request (0x8a, 0x26fe)", 0x008A, 0x26FE),
    LINK_CHECK,
    one_byte_read("usb speed byte", 0x008E, 0x0000),
    STATUS_REGISTER,
    register_read(0x06),
    register_read(0x31),
    register_read(0x33),
    register_read(0x36),
)


def utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def emit(record: dict) -> None:
    print(json.dumps({"time": utc_timestamp(), **record}), flush=True)


def find_scanner():
    for vendor_id, product_id in KNOWN_IDENTITIES:
        device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if device is not None:
            return device
    return None


def describe_device(device) -> dict:
    return {
        "kind": "device",
        "vendor_id": f"{device.idVendor:04x}",
        "product_id": f"{device.idProduct:04x}",
        "bcd_device": f"{device.bcdDevice:04x}",
        "is_gl128": device.bcdDevice == GL128_BCD_DEVICE,
        "manufacturer_index": device.iManufacturer,
        "product_index": device.iProduct,
        "bus": device.bus,
        "address": device.address,
    }


def read_language_ids(device) -> dict:
    try:
        return {"kind": "language_ids", "ids": [f"{language:04x}" for language in usb.util.get_langids(device)]}
    except usb.core.USBError as error:
        return {"kind": "language_ids", "error": str(error)}


def read_string(device, index: int) -> dict:
    try:
        return {"kind": "string", "index": index, "text": usb.util.get_string(device, index)}
    except (usb.core.USBError, ValueError) as error:
        return {"kind": "string", "index": index, "error": str(error)}


def perform_vendor_read(device, read: VendorRead) -> dict:
    record: dict = {"kind": "vendor_read", "name": read.name, "request": f"{read.request:02x}",
              "value": f"{read.value:04x}", "index": f"{read.index:04x}", "length": read.length}
    try:
        data = device.ctrl_transfer(VENDOR_IN, read.request, read.value, read.index,
                                    read.length, TIMEOUT_MILLISECONDS)
        record["returned"] = bytes(data).hex(" ")
    except usb.core.USBError as error:
        record["error"] = str(error)
    return record


def read_interrupt_once(device, timeout_milliseconds: int) -> dict:
    record: dict = {"kind": "interrupt", "endpoint": f"{INTERRUPT_ENDPOINT:02x}"}
    try:
        data = device.read(INTERRUPT_ENDPOINT, 1, timeout_milliseconds)
        record["returned"] = bytes(data).hex(" ")
    except usb.core.USBTimeoutError:
        record["returned"] = None
    except usb.core.USBError as error:
        record["error"] = str(error)
    return record


def probe_once(device) -> None:
    emit(describe_device(device))
    emit(read_language_ids(device))
    for index in (device.iManufacturer, device.iProduct, 11):
        emit(read_string(device, index))
    for read in VENDOR_READS:
        emit(perform_vendor_read(device, read))
    try:
        usb.util.claim_interface(device, 0)
        emit(read_interrupt_once(device, 200))
        usb.util.release_interface(device, 0)
    except usb.core.USBError as error:
        emit({"kind": "interface", "error": str(error)})


def same_device(device, candidate) -> bool:
    return candidate is not None and (candidate.bus, candidate.address) == (device.bus, device.address)


def watch(device, interval_seconds: float, reads: tuple) -> None:
    """Poll the status reads until this device leaves the bus.

    A scanner that went to standby and was woken again re-enumerates at a
    new address; that counts as gone, because this handle is stale.
    """
    while True:
        for read in reads:
            record = perform_vendor_read(device, read)
            emit(record)
            if "error" in record and not same_device(device, find_scanner()):
                emit({"kind": "gone"})
                return
        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only probe of an OpticFilm 120 over USB.")
    parser.add_argument("--watch", type=float, metavar="SECONDS",
                        help="after the probe, poll status every SECONDS until the device disappears")
    parser.add_argument("--gpio", action="store_true",
                        help="also poll registers 0x31 and 0x33 in watch mode (film holder test)")
    arguments = parser.parse_args()
    if arguments.gpio and not arguments.watch:
        parser.error("--gpio needs --watch")
    device = find_scanner()
    if device is None:
        emit({"kind": "absent"})
        return 1
    probe_once(device)
    if arguments.watch:
        extra_reads = GPIO_READS if arguments.gpio else ()
        watch(device, arguments.watch, (LINK_CHECK, STATUS_REGISTER) + extra_reads)
    return 0


if __name__ == "__main__":
    sys.exit(main())
