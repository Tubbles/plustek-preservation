"""Tests for decode.py on synthetic USBPcap records in pcap and pcapng form.

Run: python3 -I -m unittest discover -s tools/usbpcap
"""

import contextlib
import hashlib
import io
import json
import os
import struct
import tempfile
import unittest

import decode

REGISTER_WRITE_SETUP = bytes.fromhex("4004830000000200")  # SANE write_register framing
REGISTER_WRITE_DATA = bytes.fromhex("0b6c")
BULK_PAYLOAD = bytes(range(100))


def usbpcap_record(irp_id, info, device, endpoint, transfer_type, data, stage=None, status=0):
    """A USBPcap pseudo header plus data, as USBPcap writes it."""
    header_length = decode.USBPCAP_HEADER_LENGTH + (0 if stage is None else 1)
    header = struct.pack(decode.USBPCAP_HEADER_FORMAT, header_length, irp_id, status,
                         0x17, info, 3, device, endpoint, transfer_type, len(data))
    stage_byte = b"" if stage is None else bytes([stage])
    return header + stage_byte + data


def control_write_submit(device=1):
    return usbpcap_record(0x1234, 0, device, 0x00, 2,
                          REGISTER_WRITE_SETUP + REGISTER_WRITE_DATA, stage=0)


def bulk_in_completion(device=1):
    return usbpcap_record(0x5678, 1, device, 0x81, 3, BULK_PAYLOAD)


def pcap_file(records, byte_order="<"):
    """Classic pcap: global header, then (seconds, microseconds, payload) records."""
    output = struct.pack(byte_order + "IHHiIII", decode.PCAP_MAGIC_MICROSECONDS,
                         2, 4, 0, 0, 65535, decode.LINK_TYPE_USBPCAP)
    for seconds, microseconds, payload in records:
        output += struct.pack(byte_order + "IIII", seconds, microseconds,
                              len(payload), len(payload)) + payload
    return output


def pcapng_block(block_type, body):
    padded = body + bytes(-len(body) % 4)
    length = len(padded) + 12
    return struct.pack("<II", block_type, length) + padded + struct.pack("<I", length)


def pcapng_section():
    return pcapng_block(decode.PCAPNG_SECTION_HEADER_BLOCK,
                        struct.pack("<IHHq", decode.PCAPNG_BYTE_ORDER_MAGIC, 1, 0, -1))


def pcapng_interface(resolution_exponent):
    options = struct.pack("<HHB3x", decode.PCAPNG_OPTION_TIMESTAMP_RESOLUTION, 1,
                          resolution_exponent) + struct.pack("<HH", 0, 0)
    return pcapng_block(decode.PCAPNG_INTERFACE_DESCRIPTION_BLOCK,
                        struct.pack("<HHI", decode.LINK_TYPE_USBPCAP, 0, 65535) + options)


def pcapng_packet(timestamp_units, payload):
    body = struct.pack("<IIIII", 0, timestamp_units >> 32, timestamp_units & 0xFFFFFFFF,
                       len(payload), len(payload)) + payload
    return pcapng_block(decode.PCAPNG_ENHANCED_PACKET_BLOCK, body)


def pcapng_file(records, resolution_exponent):
    """pcapng: section, one interface with if_tsresol, enhanced packet blocks."""
    packets = b"".join(pcapng_packet(timestamp_units, payload)
                       for timestamp_units, payload in records)
    return pcapng_section() + pcapng_interface(resolution_exponent) + packets


def run_main(capture):
    """Run decode.main on capture bytes; return (exit code, stdout lines, stderr)."""
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "synthetic.pcap")
        with open(path, "wb") as capture_file:
            capture_file.write(capture)
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            exit_code = decode.main([path])
    return exit_code, output.getvalue().splitlines(), errors.getvalue()


class PcapTest(unittest.TestCase):
    def setUp(self):
        capture = pcap_file([(1000, 250000, control_write_submit()),
                             (1001, 500000, bulk_in_completion())])
        self.transfers = list(decode.iterate_transfers(capture, None))

    def test_control_setup_is_split_from_out_data(self):
        transfer = self.transfers[0]
        self.assertEqual(transfer["frame"], 1)
        self.assertEqual(transfer["timestamp"], 1000.25)
        self.assertEqual(transfer["event"], "submit")
        self.assertEqual(transfer["transfer_type"], "control")
        self.assertEqual(transfer["direction"], "out")
        self.assertEqual(transfer["control_stage"], "setup")
        self.assertEqual(transfer["setup"], {"bmRequestType": 0x40, "bRequest": 0x04,
                                             "wValue": 0x83, "wIndex": 0, "wLength": 2})
        self.assertEqual(transfer["data_length"], 2)
        self.assertEqual(transfer["data_hex"], "0b6c")
        self.assertEqual(transfer["irp_id"], "0x0000000000001234")

    def test_long_bulk_completion_is_cut_with_hash(self):
        transfer = self.transfers[1]
        self.assertEqual(transfer["frame"], 2)
        self.assertEqual(transfer["relative_time"], 1.25)
        self.assertEqual(transfer["event"], "complete")
        self.assertEqual(transfer["direction"], "in")
        self.assertEqual(transfer["endpoint"], 0x81)
        self.assertEqual(transfer["data_length"], 100)
        self.assertEqual(transfer["data_hex"], BULK_PAYLOAD[:64].hex())
        self.assertTrue(transfer["data_truncated"])
        self.assertEqual(transfer["captured_sha256"], hashlib.sha256(BULK_PAYLOAD).hexdigest())
        self.assertNotIn("captured_length", transfer)
        self.assertNotIn("setup", transfer)

    def test_record_cut_at_snapshot_length_hashes_captured_bytes(self):
        cut_record = bulk_in_completion()[:decode.USBPCAP_HEADER_LENGTH + 70]
        transfer = list(decode.iterate_transfers(pcap_file([(1, 0, cut_record)]), None))[0]
        self.assertEqual(transfer["data_length"], 100)
        self.assertEqual(transfer["captured_length"], 70)
        self.assertEqual(transfer["captured_sha256"],
                         hashlib.sha256(BULK_PAYLOAD[:70]).hexdigest())

    def test_big_endian_file_header(self):
        capture = pcap_file([(7, 0, control_write_submit())], byte_order=">")
        transfers = list(decode.iterate_transfers(capture, None))
        self.assertEqual(transfers[0]["timestamp"], 7.0)
        self.assertEqual(transfers[0]["data_hex"], "0b6c")

    def test_device_filter(self):
        capture = pcap_file([(1, 0, control_write_submit(device=5)),
                             (2, 0, bulk_in_completion(device=9))])
        transfers = list(decode.iterate_transfers(capture, 9))
        self.assertEqual([transfer["frame"] for transfer in transfers], [2])


class PcapngTest(unittest.TestCase):
    def test_records_and_nanosecond_resolution(self):
        capture = pcapng_file([(1_500_000_000_123_456_789, control_write_submit()),
                               (1_500_000_001_000_000_000, bulk_in_completion())],
                              resolution_exponent=9)
        transfers = list(decode.iterate_transfers(capture, None))
        self.assertEqual([transfer["frame"] for transfer in transfers], [1, 2])
        self.assertAlmostEqual(transfers[0]["timestamp"], 1_500_000_000.123456789, places=5)
        self.assertEqual(transfers[0]["setup"]["wValue"], 0x83)
        self.assertEqual(transfers[0]["data_hex"], "0b6c")
        self.assertEqual(transfers[1]["captured_sha256"],
                         hashlib.sha256(BULK_PAYLOAD).hexdigest())

    def test_default_resolution_is_microseconds(self):
        self.assertEqual(decode.timestamp_resolution(6), 1e-6)
        self.assertEqual(decode.timestamp_resolution(0x80 | 10), 2.0 ** -10)


class CommandLineTest(unittest.TestCase):
    def test_pcap_shorter_than_its_file_header_is_an_error(self):
        exit_code, lines, errors = run_main(pcap_file([])[:20])
        self.assertEqual(exit_code, 1)
        self.assertEqual(lines, [])
        self.assertIn("truncated pcap file header", errors)

    def test_packet_before_interface_description_is_an_error(self):
        capture = pcapng_section() + pcapng_packet(0, control_write_submit())
        exit_code, lines, errors = run_main(capture)
        self.assertEqual(exit_code, 1)
        self.assertEqual(lines, [])
        self.assertIn("frame 1: packet refers to interface 0", errors)

    def test_truncated_final_pcapng_block_is_an_error_after_complete_records(self):
        capture = pcapng_file([(0, control_write_submit()), (1, bulk_in_completion())], 6)
        exit_code, lines, errors = run_main(capture[:-10])
        self.assertEqual(exit_code, 1)
        self.assertEqual([json.loads(line)["frame"] for line in lines], [1])
        self.assertIn("truncated pcapng block", errors)

    def test_main_prints_one_json_object_per_record(self):
        capture = pcap_file([(1, 0, control_write_submit()), (2, 0, bulk_in_completion())])
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "synthetic.pcap")
            with open(path, "wb") as capture_file:
                capture_file.write(capture)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = decode.main([path, "--device", "1"])
        lines = output.getvalue().splitlines()
        self.assertEqual(exit_code, 0)
        self.assertEqual([json.loads(line)["frame"] for line in lines], [1, 2])


if __name__ == "__main__":
    unittest.main()
