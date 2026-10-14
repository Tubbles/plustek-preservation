"""Tests for keep_awake.py against a simulated GPIO block, no USB needed.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import contextlib
import io
import sys
import types
import unittest

if "usb.core" not in sys.modules:
    usb_stub = types.ModuleType("usb")
    usb_core_stub = types.ModuleType("usb.core")
    setattr(usb_core_stub, "USBError", type("USBError", (Exception,), {}))
    setattr(usb_stub, "core", usb_core_stub)
    sys.modules["usb"] = usb_stub
    sys.modules["usb.core"] = usb_core_stub

import flash_dump
import keep_awake


class FakeGpio:
    """GPIO1 to 8: 0x31 holds the output latch, 0x34 the output enables.

    A read of 0x31 returns the pin levels, as on the real chip: the latch
    bit where the output is enabled, the external level elsewhere. A pin
    in external_low is held low by something on the board even when driven.
    """

    def __init__(self, latch=0x00, enables=0x00, external=0xBC, external_low=0x00,
                 latch_stuck=False, enables_stuck=False, short_read_number=None, link_byte=0x55):
        self.latch = latch
        self.enables = enables
        self.external = external
        self.external_low = external_low
        self.latch_stuck = latch_stuck
        self.enables_stuck = enables_stuck
        self.short_read_number = short_read_number
        self.link_byte = link_byte
        self.reads = 0
        self.writes = []

    def pins(self):
        driven = (self.latch & self.enables) | (self.external & ~self.enables)
        return driven & ~self.external_low & 0xFF

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        if (request_type, request, value, index) == (0x40, 0x04, 0x0083, 0):
            register, new_value = bytes(data_or_length)
            self.writes.append((register, new_value))
            if register == 0x31 and not self.latch_stuck:
                self.latch = new_value
            elif register == 0x34 and not self.enables_stuck:
                self.enables = new_value
            return 2
        if (request_type, request, value, index & 0xFF, data_or_length) == (0xC0, 0x04, 0x008E, 0x22, 2):
            self.reads += 1
            register_value = {0x31: self.pins(), 0x34: self.enables}[index >> 8]
            reply = bytes((register_value, self.link_byte))
            return reply[:1] if self.reads == self.short_read_number else reply
        raise AssertionError(f"unexpected request {request_type:02x} {request:02x} {value:04x} {index:04x}")


def run_keep_awake(fake):
    with contextlib.redirect_stdout(io.StringIO()):
        return keep_awake.run(flash_dump.Session(fake, io.StringIO()))


class KeepAwakeTests(unittest.TestCase):
    def test_owner_unit_gets_the_level_written_before_the_enable(self):
        fake = FakeGpio(latch=0x00, enables=0x00, external=0xBC)
        self.assertEqual(run_keep_awake(fake), 0)
        self.assertEqual(fake.writes, [(0x31, 0xBC), (0x34, 0x80)])
        self.assertTrue(fake.pins() & 0x80)

    def test_level_is_written_even_when_the_pin_already_reads_high(self):
        fake = FakeGpio(latch=0x00, external=0xFF)
        run_keep_awake(fake)
        self.assertEqual(fake.writes[0], (0x31, 0xFF))
        self.assertTrue(fake.latch & 0x80)

    def test_other_enable_bits_are_kept(self):
        fake = FakeGpio(enables=0x05)
        self.assertEqual(run_keep_awake(fake), 0)
        self.assertEqual(fake.writes[1], (0x34, 0x85))

    def test_pin_held_low_rolls_the_enable_back(self):
        fake = FakeGpio(enables=0x00, external_low=0x80)
        self.assertEqual(run_keep_awake(fake), keep_awake.EXIT_NOT_CONFIRMED)
        self.assertEqual(fake.writes[-1], (0x34, 0x00))
        self.assertEqual(fake.enables, 0x00)

    def test_latch_that_does_not_take_the_level_rolls_the_enable_back(self):
        fake = FakeGpio(latch=0x00, latch_stuck=True)
        self.assertEqual(run_keep_awake(fake), keep_awake.EXIT_NOT_CONFIRMED)
        self.assertEqual(fake.enables, 0x00)

    def test_rollback_clears_an_enable_that_was_already_set(self):
        fake = FakeGpio(enables=0x81, external_low=0x80)
        self.assertEqual(run_keep_awake(fake), keep_awake.EXIT_NOT_CONFIRMED)
        self.assertEqual(fake.enables, 0x01)

    def test_enable_that_does_not_take_is_not_reported_as_success(self):
        fake = FakeGpio(external=0xBC, enables_stuck=True)
        self.assertEqual(run_keep_awake(fake), keep_awake.EXIT_NOT_CONFIRMED)

    def test_failed_read_after_the_enable_still_rolls_it_back(self):
        for read_number in (3, 4):
            with self.subTest(read_number=read_number):
                fake = FakeGpio(latch_stuck=True, short_read_number=read_number)
                self.assertEqual(run_keep_awake(fake), flash_dump.EXIT_USB_ERROR)
                self.assertEqual(fake.writes[-1], (0x34, 0x00))
                self.assertEqual(fake.enables, 0x00)

    def test_wrong_link_byte_stops_before_any_write(self):
        fake = FakeGpio(link_byte=0xAA)
        self.assertEqual(run_keep_awake(fake), flash_dump.EXIT_USB_ERROR)
        self.assertEqual(fake.writes, [])

    def test_other_registers_are_refused(self):
        fake = FakeGpio()
        with self.assertRaises(PermissionError):
            keep_awake.write_register(flash_dump.Session(fake, io.StringIO()), 0x36, 0x80)
        self.assertEqual(fake.writes, [])


if __name__ == "__main__":
    unittest.main()
