"""Search binaries for byte patterns that USB descriptors would leave.

Looks for device descriptor headers, the OpticFilm 120 and Genesys default
VID/PID pairs in little-endian order, and the product and manufacturer strings
in ASCII and UTF-16LE (the encoding of USB string descriptors). Prints one line
per hit: file, pattern name, file offset.

Usage: python3 -I tools/ghidra/find_descriptor_bytes.py <file> [<file> ...]
"""

import sys

TEXT_PATTERNS = ["Film Scanner", "USB2.0 Scanner", "Genesys", "Plustek", "GENESYS"]

BYTE_PATTERNS = {
    "device descriptor header, USB 2.0": bytes.fromhex("12010002"),
    "device descriptor header, USB 1.1": bytes.fromhex("12011001"),
    "VID 07b3 PID 1406, little-endian": bytes.fromhex("b3070614"),
    "VID 05e3 PID 0103, little-endian": bytes.fromhex("e3050301"),
    "VID 07b3 PID 1440, little-endian": bytes.fromhex("b3074014"),
}


def all_patterns():
    patterns = dict(BYTE_PATTERNS)
    for text in TEXT_PATTERNS:
        patterns["ascii " + repr(text)] = text.encode("ascii")
        patterns["utf-16le " + repr(text)] = text.encode("utf-16-le")
    return patterns


def find_all(data, needle):
    offset = data.find(needle)
    while offset != -1:
        yield offset
        offset = data.find(needle, offset + 1)


def main(paths):
    patterns = all_patterns()
    for path in paths:
        with open(path, "rb") as handle:
            data = handle.read()
        for name, needle in patterns.items():
            for offset in find_all(data, needle):
                print(f"{path}\t{name}\t0x{offset:x}")


if __name__ == "__main__":
    main(sys.argv[1:])
