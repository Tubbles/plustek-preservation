"""Tests for annotate_gl128.py on both USBPcap control transfer layouts.

Run: python3 -I -m unittest discover -s tools/usbpcap
"""

import unittest

import annotate_gl128
import decode
from test_decode import REGISTER_WRITE_DATA, REGISTER_WRITE_SETUP, pcap_file, usbpcap_record

# SANE register read framing: 0xc0/0x04, wValue 0x8e, wIndex 0x22 + (0x41 << 8), wLength 2.
REGISTER_READ_SETUP = bytes.fromhex("c0048e0022410200")
REGISTER_READ_DATA = bytes.fromhex("1055")  # value 0x10, then the 0x55 link byte

STAGE_SETUP, STAGE_DATA, STAGE_STATUS, STAGE_COMPLETE = 0, 1, 2, 3
SUBMIT, COMPLETE = 0, 1


def control_record(irp_id, info, endpoint, data, stage):
    return usbpcap_record(irp_id, info, 1, endpoint, 2, data, stage=stage)


def layout_before_1_5():
    """Setup, data and status records per control transfer (USBPcap < 1.5.0.0)."""
    return [
        control_record(0x2000, SUBMIT, 0x00, REGISTER_WRITE_SETUP, STAGE_SETUP),
        control_record(0x2000, SUBMIT, 0x00, REGISTER_WRITE_DATA, STAGE_DATA),
        control_record(0x2000, COMPLETE, 0x00, b"", STAGE_STATUS),
        control_record(0x3000, SUBMIT, 0x80, REGISTER_READ_SETUP, STAGE_SETUP),
        control_record(0x3000, COMPLETE, 0x80, REGISTER_READ_DATA, STAGE_DATA),
        control_record(0x3000, COMPLETE, 0x80, b"", STAGE_STATUS),
    ]


def layout_since_1_5():
    """Setup record with OUT data, complete record with IN data (USBPcap >= 1.5.0.0)."""
    return [
        control_record(0x2000, SUBMIT, 0x00, REGISTER_WRITE_SETUP + REGISTER_WRITE_DATA,
                       STAGE_SETUP),
        control_record(0x2000, COMPLETE, 0x00, b"", STAGE_COMPLETE),
        control_record(0x3000, SUBMIT, 0x80, REGISTER_READ_SETUP, STAGE_SETUP),
        control_record(0x3000, COMPLETE, 0x80, REGISTER_READ_DATA, STAGE_COMPLETE),
    ]


def operations(records):
    capture = pcap_file([(1, 0, record) for record in records])
    transfers = decode.iterate_transfers(capture, None)
    return [annotate_gl128.describe(transaction)
            for transaction in annotate_gl128.pair_transactions(transfers)]


class ControlLayoutTest(unittest.TestCase):
    EXPECTED_TEXTS = ["write 0x0b = 0x6c", "read 0x41 -> 0x10"]

    def test_layout_before_1_5_pairs_setup_data_and_status(self):
        result = operations(layout_before_1_5())
        self.assertEqual([operation.text for operation in result], self.EXPECTED_TEXTS)
        self.assertEqual([(operation.first_frame, operation.last_frame) for operation in result],
                         [(1, 3), (4, 6)])

    def test_layout_since_1_5(self):
        result = operations(layout_since_1_5())
        self.assertEqual([operation.text for operation in result], self.EXPECTED_TEXTS)
        self.assertEqual([(operation.first_frame, operation.last_frame) for operation in result],
                         [(1, 2), (3, 4)])


if __name__ == "__main__":
    unittest.main()
