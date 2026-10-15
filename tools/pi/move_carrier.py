"""Move the OpticFilm 120's film holder carrier once, with the requests of the vendor's move 3 or move 1.

Sends the requests Plustek's Windows driver sent to a working OpticFilm
120 for its third carrier move in the issue #151 capture, frames 6445 to
6644 (doc/protocol/of120-moves.md, "Move 3, the 97-step move"), or with
--as-move-1 for its first, with a chosen step count, and switches motor
power off at the end. It runs after vendor_open.py, whose open sequence
(capture frames 15 to 138) it does not repeat. Work item:
doc/work/0011-first-motor-move.md. The steps below are those of move 3.
"--as-move-1" further down says what changes for move 1.

Sequence:
1. Read 0x101, 0x31, 0x33, 0x36 and 0x02 and log them.
2. Gate: the run goes on only when 0x101 has PWRBIT (bit 7) set and
   MOTORENB (bit 0) clear and 0x36 reads 0xfe. Otherwise it logs a
   "refused" record and exits 22 before any OUT transfer. On the owner's
   unit 0x101 read 0x4c (PWRBIT clear) before the open of 2026-10-15 and
   0xdc after it (doc/hardware/probes/20261015T061444Z-vendor-open.jsonl),
   so a set PWRBIT means the open has run since the wake. 0x36 = 0xfe is
   the open's write at frame 115, its last GPIO output enable, so an open
   that stopped after the blast (0x36 = 0xfc) does not pass.
3. Register state: REGISTER_STATE, the 76 registers whose value at the
   start write of move 3 (frame 6483, a replay of every register write
   from frame 15) differs from the value the open sequence leaves, in
   ascending register order, 32 pairs per transfer (wValue 0x0183 for
   registers from 0x100 up, none at present). Then the AFE write of frame
   6175 as captured, one transfer of 0x51 = 0x04, 0x5d = 0x00 and
   0x5e = 0x2a, the last AFE write before move 3. test_move_carrier.py
   rebuilds the table from the capture and checks that the register state
   at the start write then differs from the capture's only in 0x03: the
   lamp stays off, while the vendor's move 3 ran with 0x03 = 0x30. With
   --lamp-as-captured the tool writes 0x03 = 0x30 after the AFE write, so
   that the state matches the capture in full, and 0x03 = 0x00 (frame 77
   of the open) after the last write of step 7. The first run without
   it, 2026-10-15 07:21 UTC, ran the step engine with the capture's
   timing but moved nothing (doc/log/2026-10-15.md). Not in
   the table: 0x0d and 0x0f (commands), and 0x02, 0x0a, 0x09, 0x33 and
   the 19 registers of the block at frame 6463, which steps 4 to 7 write.
   REGISTER_STATE writes 0x37 = 0x32 (the open leaves 0x30), which drives
   GPIO26 high (GPOE26 is set by 0x38 = 0x77,
   doc/protocol/gl128-registers.md, "Where CGL126 (the OpticFilm 120's
   class) differs"), as during move 3 and the exit move of the capture.
4. The move, frames 6445 to 6483: 0x33 = 0x1c (frame 6445, the open
   leaves 0x0e), read 0x33, 0x02 = 0x58, 0x0a = 0x48, 0x33 = the value
   read with bit 5 set, with --backscan 0x09 = 0x08 (frame 7391 of the
   reverse move), the 19-pair block of frame 6463 with FEEDL (0x3d to
   0x3f, big endian) set to --steps, then for 0x1000c000 and 0x10010000
   in turn the buffer header (40 04 0082 wIndex 0x01), the 512-byte slope
   table on bulk endpoint 0x02 (doc/protocol/tables/slope-6353.hex) and
   the one-byte read at wIndex 0x18, then 0x0f = 0x01, the start.
5. Poll 0x101 every 15 ms from the start write (the capture: 15.5 ms on
   average) and log every value with the seconds since the start write
   and its HOMESNR and MOTORENB bits, until MOTORENB clears or
   --poll-limit-seconds have passed.
6. Only when the limit passed with MOTORENB still set: the vendor's cut of
   moves 1 and 2, frames 6287 and 6291 as captured (0x02 = 0x08, then
   FEEDL = 1 in a transfer of its own), then polls as in step 5 for up to
   5 s until MOTORENB clears. The log says whether it did. The run exits
   23 either way.
7. After the move: with --backscan 0x09 = 0x00 (frame 7923, right after
   the last poll as in the capture), read 0x33, 0x02 = 0x58, 0x0a = 0x48,
   0x33 = the value read with bit 5 cleared, read 0x101 (frames 6629 to
   6644), then 0x02 = 0x08, the write the vendor sends after moves 1 and 2
   (frame 6373), so that MTRPWR is clear at the end. The vendor leaves
   0x02 = 0x58 after move 3.
8. Read and log the registers of step 1 again.

After every OUT control transfer the tool sends the link check (c0 0c
008e wIndex 0x20, 1 byte), as the capture does, and requires 0x55. Every
register read must return 0x55 as its second byte, and the read at wIndex
0x18 must return 0x02, as all 66 in the capture do. Otherwise the run
stops with exit 13, so a table upload that does not answer like the
capture stops it before the start write. No transfer is retried. The
0x33 writes after frame 6445 keep the read value except for bit 5, as the
vendor's read-modify-write does. The capture has no pause longer than
3 ms between these requests apart from the polls, so the tool sends them
back to back.

--backscan sets BACKSCAN (0x09 bit 3) for the move and clears it after,
as the capture's reverse move does at frames 7391 and 7923, and adds
nothing else: the registers and the table stay those of move 3. No move
in the capture ran like that. Against the exit move, the capture's other
move with BACKSCAN, the register state at the start write differs in 15
registers (frame 15585, two of them FEEDL, FMOVNO among the others), and
the capture has no move with BACKSCAN that starts off the home sensor
(doc/protocol/of120-moves.md, "Direction"). Without --backscan neither
variant writes 0x09, and the gate does not read it: a --backscan run
that stopped between its two 0x09 writes leaves bit 3 set for the next
run of the same wake, until the open writes 0x09 = 0x00 again (frame
17).

--as-move-1 replays the vendor's move 1 instead, with FEEDL from --steps
(doc/protocol/of120-moves.md, "Move 1 (frames 6257 to 6344)"). Steps 1,
2, 5 and 6 stay as above. Step 3 sends REGISTER_STATE_MOVE_1, the 74
registers whose value at the start write of move 1 (frame 6279) differs
from the value the open leaves, the 27 registers of the block at frame
6259 left out, then the AFE write of frame 6175. Step 4 is 0x33 = 0x1c
(frame 6085, the vendor's last write of 0x33 before move 1, bit 5 clear;
the vendor read 0x33 = 0x1e at frame 6083 first, the tool writes the
value without a read), the 27-pair block of frame 6259 as captured with
FEEDL set to --steps, the table pair of frames 6263 to 6277 with
doc/protocol/tables/slope-6267.hex, then the start (frame 6279). From
frame 6257 to the start the vendor sends nothing else but an interrupt
read (frame 6257), which the tool leaves out: 0x02 = 0x18 and 0x03 =
0x30 are in the block, 0x0a = 0x48 is the open's value and was last
written at frame 6189. So the lamp is on during the move, as in the
capture, and it stays on if the run stops between the block and step 7
(exit 13, Ctrl-C). During the move the vendor read 0x101 once (frame
6283) and then waited 3.9 s on an interrupt read (frame 6285) whose
answer 0x40 ended the move; the tool polls 0x101 every 15 ms instead and
has no interrupt read pending. Step 7 is 0x02 = 0x08 (as the vendor's
cut, frame 6287), 0x03 = 0x00 (frame 77 of the open) and a read of
0x101, whose captured value 0xf4 (frame 6327, lamp still on there) is
expected to differ in LAMPSTS. Nothing of what the vendor sends after
move 1 to set up move 2 is sent. test_move_carrier.py
checks that the register state at the start write then equals the
capture's at frame 6279 in full apart from FEEDL (10158 in the capture,
above the limit of --steps). Against the state the move 3 variant
starts with, it differs in 0x33 (0x1c against 0x3c), FMOVNO (0xaf = 0x7f
against 0xff) and the lamp (0x03 = 0x30 against 0x00), FEEDL being
--steps in both. --backscan and --lamp-as-captured are refused with
--as-move-1 (argparse error, exit 2): the capture has no move 1 with
BACKSCAN, and the block switches the lamp on itself.

Safety, checked before every transfer: check_allowed lets through only
the OUT requests, link checks and reads at wIndex 0x18 listed above for
the variant of the run, with its --steps and --backscan. A 0x33 write
other than the fixed one (frame 6445, or 6085 for move 1) may differ from
the last value read from 0x33 in bit 5 only, and a move 1 run reads 0x33
only in steps 1 and 8. Register reads go through vendor_open.read_register
and only for the registers of step 1. Anything else raises before the
transfer. There is no flash request, no interrupt read and no other write.
The allow-list checks content, not order: the order is that of the code,
which runs straight through, and test_move_carrier.py checks the exact
sequence. Before the first transfer, the table payloads the run will send
are checked against the SHA-256 in doc/protocol/tables/README.md.

Before a run: ~/plustek-preservation/probe-disabled exists, keep_awake.py
does not run, and vendor_open.py has run since the wake and has finished
(run it with --watch-seconds 0, or wait for its watch to end: its polls
would land between the move's requests). The film holder stays out of the
unit and the owner stays at the power switch. The direction is decided
beforehand: without --backscan the carrier moves away from the home
sensor (inference, doc/protocol/of120-moves.md, "Direction"). The tool
refuses to start while the file is missing or a probe_readonly.py,
keep_awake.py, vendor_open.py, flash_dump.py, eeprom_read.py,
snapshot.py or other move_carrier.py process runs. Each run needs the
owner's go-ahead.

Every run writes LOG_DIRECTORY/<UTC stamp>/log.jsonl: one line per request
(kind, the capture frame it replays, setup fields, bytes sent or the
SHA-256 of the table, bytes received, the captured answer where the
capture has one), one per link check, one per poll.

Exit codes (1 and 2 are left to Python and argparse): 0 MOTORENB cleared
within the poll limit and every write after the move was acknowledged, 10
scanner not found, 13 USB error, short transfer, link byte other than
0x55, read at wIndex 0x18 other than 0x02 or refused request (the log
names the request), 16 probe-disabled missing or another scanner tool
running, 19 bcdDevice other than 0x0702, 22 the gate refused the run
(PWRBIT clear, MOTORENB set or 0x36 other than 0xfe, no OUT transfer
sent), 23 MOTORENB still set when the poll limit passed (the cut and the
writes of step 7 were sent), 24 a table payload does not match its
SHA-256 (nothing sent).

Usage (on the Pi):
    sudo ~/plustek-preservation/venv/bin/python move_carrier.py LOG_DIRECTORY [--steps N] [--backscan]
        [--poll-limit-seconds S] [--lamp-as-captured] [--as-move-1]
"""

import argparse
import dataclasses
import hashlib
import math
import os
import pathlib
import struct
import sys
import typing

import usb.core

import vendor_open
from flash_dump import (EXIT_NOT_FOUND, EXIT_PROBE_ACTIVE, EXIT_USB_ERROR, TIMEOUT_MILLISECONDS, Session,
                        ShortTransferError, control_in, find_scanner, log, new_run_directory, request_code_for)
from keep_awake import EXIT_WRONG_CHIP, GL128_BCD_DEVICE, LinkByteError
from vendor_open import (EXIT_GOOD, HOMESNR_BIT, MOTORENB_BIT, REGISTER_WRITE_VALUE, STATUS_REGISTER, VENDOR_IN,
                         VENDOR_OUT, Environment, require_link_byte, wait_until)

HIGH_REGISTER_WRITE_VALUE = 0x0183
BUFFER_HEADER_VALUE = 0x0082
BUFFER_HEADER_INDEX = 0x01
LINK_CHECK_INDEX = 0x0020
UPLOAD_STATUS_INDEX = 0x0018
UPLOAD_STATUS_ANSWER = b"\x02"
CONTROL_ENDPOINT = 0x00
BULK_OUT_ENDPOINT = 0x02
PAIRS_PER_TRANSFER = 32
PWRBIT = 0x80
GPIO_OUTPUT_ENABLE_REGISTER = 0x36
OPEN_GPIO_OUTPUT_ENABLE = 0xFE  # written at frame 115, the open's last GPIO output enable
REGISTER_33_MOVE_BIT = 0x20  # set for moves 2, 3 and both moves with BACKSCAN, by read-modify-write
LOGGED_REGISTERS = (STATUS_REGISTER, 0x31, 0x33, GPIO_OUTPUT_ENABLE_REGISTER, 0x02)
DEFAULT_STEPS = 97
MAXIMUM_STEPS = 1000
POLL_INTERVAL_SECONDS = 0.015
DEFAULT_POLL_LIMIT_SECONDS = 10.0
AFTER_CUT_POLL_LIMIT_SECONDS = 5.0
TABLE_ADDRESSES = (0x1000C000, 0x10010000)
# probe_readonly.py and keep_awake.py are refused by vendor_open.refusal_exit_code.
CONFLICTING_TOOL_NAMES = (b"vendor_open.py", b"move_carrier.py", b"flash_dump.py", b"eeprom_read.py", b"snapshot.py")

EXIT_OPEN_NOT_SENT = 22
EXIT_MOTOR_TIMEOUT = 23
EXIT_TABLE_HASH = 24

# Registers whose value at the start write of move 3 (capture frame 6483) differs from the value OPEN_SEQUENCE
# leaves, as (register, value) in ascending order. test_move_carrier.py rebuilds this from the capture.
REGISTER_STATE = (
    (0x04, 0x42), (0x13, 0x08), (0x16, 0xB7), (0x18, 0x40), (0x1D, 0x20), (0x20, 0x05), (0x22, 0x06), (0x24, 0x0F),
    (0x28, 0x00), (0x29, 0x55), (0x2A, 0x8A), (0x2C, 0x01), (0x2D, 0xE0), (0x31, 0xFC), (0x37, 0x32), (0x52, 0x08),
    (0x53, 0x0A), (0x54, 0x00), (0x55, 0x02), (0x56, 0x04), (0x57, 0x06), (0x58, 0x07), (0x59, 0x07), (0x5A, 0x11),
    (0x5B, 0x49), (0x5F, 0x00), (0x61, 0x98), (0x70, 0x02), (0x71, 0x03), (0x72, 0x04), (0x73, 0x05), (0x76, 0x3F),
    (0x79, 0x3F), (0x7C, 0x3F), (0x81, 0x11), (0x83, 0x02), (0x84, 0x44), (0x86, 0x17), (0x87, 0xAC), (0x88, 0x00),
    (0x89, 0x00), (0xA0, 0x0A), (0xA2, 0x00), (0xA3, 0x00), (0xA5, 0x26), (0xAB, 0x26), (0xAC, 0x00), (0xAD, 0x01),
    (0xD0, 0x0A), (0xD1, 0x0A), (0xD2, 0x0A), (0xE0, 0x00), (0xE1, 0xC8), (0xE2, 0x15), (0xE3, 0xFB), (0xE4, 0x15),
    (0xE5, 0xFC), (0xE6, 0x2B), (0xE7, 0x2F), (0xE8, 0x2B), (0xE9, 0x30), (0xEA, 0x40), (0xEB, 0x63), (0xEC, 0x40),
    (0xED, 0x64), (0xEE, 0x55), (0xEF, 0x97), (0xF0, 0x55), (0xF1, 0x98), (0xF2, 0x6A), (0xF3, 0xCB), (0xF4, 0x6A),
    (0xF5, 0xCC), (0xF6, 0x7F), (0xF7, 0xFF), (0xF8, 0x05),
)

# The same for move 1 (start write at frame 6279), the 27 registers of its block at frame 6259 left out.
# test_move_carrier.py rebuilds this from the capture.
REGISTER_STATE_MOVE_1 = (
    (0x13, 0x08), (0x16, 0xB7), (0x18, 0x40), (0x20, 0x05), (0x22, 0x06), (0x24, 0x0F), (0x28, 0x00), (0x29, 0x55),
    (0x2A, 0x8A), (0x31, 0xFC), (0x37, 0x32), (0x52, 0x08), (0x53, 0x0A), (0x54, 0x00), (0x55, 0x02), (0x56, 0x04),
    (0x57, 0x06), (0x58, 0x07), (0x59, 0x07), (0x5A, 0x11), (0x5B, 0x49), (0x5F, 0x00), (0x61, 0x98), (0x70, 0x02),
    (0x71, 0x03), (0x72, 0x04), (0x73, 0x05), (0x76, 0x3F), (0x79, 0x3F), (0x7C, 0x3F), (0x88, 0x00), (0x89, 0x00),
    (0x8A, 0x00), (0x8B, 0x55), (0x8C, 0x00), (0x8D, 0x00), (0x8E, 0x55), (0x8F, 0x00), (0x90, 0x01), (0x91, 0x54),
    (0x92, 0x00), (0xA0, 0x0A), (0xA2, 0x00), (0xA3, 0x00), (0xAC, 0x00), (0xAD, 0x01), (0xD0, 0x0A), (0xD1, 0x0A),
    (0xD2, 0x0A), (0xE0, 0x00), (0xE1, 0xC8), (0xE2, 0x15), (0xE3, 0xFB), (0xE4, 0x15), (0xE5, 0xFC), (0xE6, 0x2B),
    (0xE7, 0x2F), (0xE8, 0x2B), (0xE9, 0x30), (0xEA, 0x40), (0xEB, 0x63), (0xEC, 0x40), (0xED, 0x64), (0xEE, 0x55),
    (0xEF, 0x97), (0xF0, 0x55), (0xF1, 0x98), (0xF2, 0x6A), (0xF3, 0xCB), (0xF4, 0x6A), (0xF5, 0xCC), (0xF6, 0x7F),
    (0xF7, 0xFF), (0xF8, 0x05),
)

# The 27 pairs of frame 6259 as captured (FEEDL 10158, lamp 0x03 = 0x30). move_1_block() replaces FEEDL.
MOVE_1_BLOCK_CAPTURED = bytes.fromhex("0330 7d00 7e99 7f99 8000 8111 8200 8302 8444 8500 8617 87ac 2c01 2de0 0442 1d20"
                                      " 1c00 a400 a526 aa00 ab26 0218 ae00 af7f 3d00 3e27 3fae")
MOVE_1_FEEDL_VALUE_POSITIONS = slice(49, 54, 2)  # the values of 0x3d, 0x3e and 0x3f in MOVE_1_BLOCK_CAPTURED

# The 19 pairs of frame 6463 as captured (FEEDL 97). feed_block() replaces the FEEDL values.
FEED_BLOCK_CAPTURED = bytes.fromhex("1c00 3d00 3e00 3f61 7d00 7e99 7f99 8a00 8b55 8c00 8d00 8e55 8f00 9001 9154 9200"
                                    " 0218 ae00 afff")
FEEDL_VALUE_POSITIONS = slice(3, 8, 2)  # the values of 0x3d, 0x3e and 0x3f in FEED_BLOCK_CAPTURED

# doc/protocol/tables/slope-6353.hex, sent at frames 6471 and 6479. SHA-256 from doc/protocol/tables/README.md.
SLOPE_TABLE_SHA256 = "6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4"
SLOPE_TABLE = bytes.fromhex(
    "8cbe97cd3d96027c816ca861cc590154ea4e1e4b0547ef43a641013f093d2f3b"
    "7139cd37a23625351534bb32c231d430ed2fc82ef42d6b2da42ce32b292b752a"
    "002a5629b0284528a8274227ac264b26ec2561250625ad245624d62382233123"
    "e02291224322f72187213e21f620b0208d2048200420c21f801f401f001fc21e"
    "841e661e2a1eee1db41d971d5e1d261def1cd41c9e1c681c4e1c1a1ce61bcd1b"
    "9b1b691b511b201b081bd81ac11a921a7b1a4e1a371a0a1af419c819b2198719"
    "7219481933190a19f518cd18b918a5187d186a1843182f181c18f617e417d117"
    "ac179a1788176417521740171d170b17fa16d716c616b516a516831673166216"
    "52163116211611160116e215d215c315b315a415851576156715581549152c15"
    "1d150e150015f114e314d514b914ab149d148f148114731465144a143d142f14"
    "221415140814fb13ee13e113d413c713ad13a113941388137b136f1362135613"
    "4a133e133213251319130e130213f612ea12de12d312c712bc12b012a5129912"
    "8e12831278126c12611256124b12401236122b12201215120a120012f511eb11"
    "e011d611cb11c111b711ac11a21198118e11841184117a11701166115c115211"
    "48113f1135112b11211118110e110e110511fb10f210e910df10d610cd10c310"
    "c310ba10b110a8109f1096108d10841084107b1072106910601058104f104610"
)

# doc/protocol/tables/slope-6267.hex, sent at frames 6267 and 6275 for move 1. SHA-256 from the same README.
SLOPE_TABLE_MOVE_1_SHA256 = "47a4f0bc51c2a53ed0298d2b2e5e4bfdb0af3a40c5d812cacb470d2934b2d7a2"
SLOPE_TABLE_MOVE_1 = bytes.fromhex(
    "515ae462b349403e36376732a42ec42b56295b27a6254024f422d221c120d21f"
    "001f381e7b1dd41c411ca71b201b9e1a2c1abd195219eb1887182f18da178817"
    "3717e9169c165a161916da159c155f152415ea14b914811451142214f413c713"
    "9a136f1344131913f612cd12aa12831261123b121a12fa11db11bc119d117f11"
    "6111431126110e11f210d610bf10a3108d1072105c1046102c1017100210ed0f"
    "d40fc00fac0f980f840f700f5d0f490f360f270f150f020ff00ee10ecf0ebd0e"
    "af0e9d0e8c0e7e0e6d0e5f0e4f0e410e310e230e160e060ef90ded0ddd0dd00d"
    "c40db70da80d9c0d900d840d780d6c0d600d540d490d3d0d320d270d1b0d100d"
    "050dfa0cef0ce40cd90cd10cc60cbb0cb10ca60c9f0c940c8a0c820c780c6e0c"
    "660c5c0c520c4b0c410c370c300c260c1f0c150c0e0c040cfd0bf40bed0be40b"
    "dd0bd40bcd0bc60bbd0bb60baf0ba60ba00b990b900b8a0b830b7b0b740b6e0b"
    "670b5f0b580b520b4c0b430b3d0b370b310b2b0b250b1c0b160b100b0a0b040b"
    "fe0af80af30aed0ae70ae10adb0ad50ad00aca0ac40abf0ab90ab30aae0aa80a"
    "a20a9d0a970a920a8c0a870a810a7c0a770a730a6e0a680a630a5e0a590a530a"
    "500a4b0a450a400a3b0a380a320a2d0a280a250a200a1b0a160a120a0e0a090a"
    "040a000afb09f709f309ee09ea09e609e209dd09da09d509d009cd09c809c409"
)


@dataclasses.dataclass(frozen=True)
class Request:
    """One transfer other than a register read: a vendor control request, or the table on the bulk endpoint."""
    kind: str
    frame: typing.Optional[int]  # the capture frame it replays, None where the capture has no single frame
    request_type: int  # 0 for the bulk transfer
    request: int
    value: int
    index: int
    sent: bytes = b""
    length: int = 0  # bytes to read, for VENDOR_IN
    captured: bytes = b""  # the working unit's answer, where the capture has one
    endpoint: int = CONTROL_ENDPOINT


@dataclasses.dataclass(frozen=True)
class RegisterRead:
    """A register read the capture has: its frame and the value the working unit gave."""
    frame: int
    register: int
    captured: int


@dataclasses.dataclass
class MovePlan:
    """What a run may send: the command line choices and the value last read from 0x33 for the move."""
    steps: int
    backscan: bool
    lamp: bool = False
    as_move_1: bool = False
    register_33_read: typing.Optional[int] = None


@dataclasses.dataclass(frozen=True)
class PollWindow:
    """Reads of 0x101 on a POLL_INTERVAL_SECONDS grid from first_poll, for at most limit_seconds."""
    phase: str
    move_start: float  # the start write, from which the log counts seconds_since_start
    first_poll: float
    limit_seconds: float


class UnexpectedAnswerError(Exception):
    pass


class StoppedAt(Exception):
    def __init__(self, kind: str, frame: typing.Optional[int]):
        super().__init__(f"stopped at {kind} (capture frame {frame})")
        self.kind = kind
        self.frame = frame


def describe(request: Request) -> str:
    return f"{request.kind} (capture frame {request.frame})"


def register_write(frame: typing.Optional[int], pairs: bytes, value: int = REGISTER_WRITE_VALUE,
                   kind: str = "register_write") -> Request:
    return Request(kind, frame, VENDOR_OUT, request_code_for(len(pairs)), value, 0x0000, pairs)


def single_write(frame: int, register: int, register_value: int) -> Request:
    return register_write(frame, bytes([register, register_value]))


def buffer_header(frame: int, address: int, size: int) -> Request:
    """Address and size of the next bulk transfer, both 32-bit little endian."""
    return Request("buffer_header", frame, VENDOR_OUT, 0x04, BUFFER_HEADER_VALUE, BUFFER_HEADER_INDEX,
                   struct.pack("<II", address, size))


def table_upload(frame: int, table: bytes) -> Request:
    return Request("bulk_write", frame, 0, 0, 0, 0, table, endpoint=BULK_OUT_ENDPOINT)


def upload_status_read(frame: int) -> Request:
    return Request("upload_status_read", frame, VENDOR_IN, 0x0C, 0x008E, UPLOAD_STATUS_INDEX, length=1,
                   captured=UPLOAD_STATUS_ANSWER)


def register_33_write(frame: int, register_value: int) -> Request:
    return single_write(frame, 0x33, register_value)


def block_with_feedl(frame: int, captured: bytes, feedl_value_positions: slice, steps: int) -> Request:
    """A captured block of register pairs with FEEDL (0x3d to 0x3f, big endian) set to steps."""
    if not 1 <= steps <= MAXIMUM_STEPS:
        raise PermissionError(f"refusing FEEDL {steps}, allowed 1 to {MAXIMUM_STEPS}")
    pairs = bytearray(captured)
    pairs[feedl_value_positions] = steps.to_bytes(3, "big")
    return register_write(frame, bytes(pairs))


def feed_block(steps: int) -> Request:
    """The 19 pairs of frame 6463 with FEEDL set to steps."""
    return block_with_feedl(6463, FEED_BLOCK_CAPTURED, FEEDL_VALUE_POSITIONS, steps)


def move_1_block(steps: int) -> Request:
    """The 27 pairs of frame 6259 with FEEDL set to steps."""
    return block_with_feedl(6259, MOVE_1_BLOCK_CAPTURED, MOVE_1_FEEDL_VALUE_POSITIONS, steps)


def split_low_and_high_registers(pairs: tuple) -> list:
    """(wValue, pairs) for the registers below 0x100 and for those from 0x100 up, empty groups left out."""
    low = [(register, value) for register, value in pairs if register <= 0xFF]
    high = [(register & 0xFF, value) for register, value in pairs if register > 0xFF]
    return [(group_value, group) for group_value, group in ((REGISTER_WRITE_VALUE, low),
                                                            (HIGH_REGISTER_WRITE_VALUE, high)) if group]


def register_state_writes(pairs: tuple) -> tuple:
    """Transfers of at most PAIRS_PER_TRANSFER pairs that set the registers in ascending order."""
    writes = []
    for group_value, group in split_low_and_high_registers(tuple(sorted(pairs))):
        for start in range(0, len(group), PAIRS_PER_TRANSFER):
            payload = bytes(byte for pair in group[start:start + PAIRS_PER_TRANSFER] for byte in pair)
            writes.append(register_write(None, payload, group_value, kind="register_state_write"))
    return tuple(writes)


REGISTER_STATE_WRITES = register_state_writes(REGISTER_STATE)
AFE_WRITE = register_write(6175, bytes.fromhex("5104 5d00 5e2a"))
LINK_CHECK = Request("link_check", None, VENDOR_IN, 0x0C, 0x008E, LINK_CHECK_INDEX, length=1, captured=b"\x55")
REGISTER_33_RESET = register_33_write(6445, 0x1C)
BEFORE_READ_0X33 = RegisterRead(6449, 0x33, 0x1C)
BEFORE_WRITE_0X02 = single_write(6451, 0x02, 0x58)
BEFORE_WRITE_0X0A = single_write(6455, 0x0A, 0x48)
BACKSCAN_SET = single_write(7391, 0x09, 0x08)
TABLE_UPLOADS = (
    (buffer_header(6467, TABLE_ADDRESSES[0], len(SLOPE_TABLE)), table_upload(6471, SLOPE_TABLE),
     upload_status_read(6473)),
    (buffer_header(6475, TABLE_ADDRESSES[1], len(SLOPE_TABLE)), table_upload(6479, SLOPE_TABLE),
     upload_status_read(6481)))
START = single_write(6483, 0x0F, 0x01)
CUT_MOTOR_POWER = single_write(6287, 0x02, 0x08)
CUT_FEEDL = register_write(6291, bytes.fromhex("3d00 3e00 3f01"))
BACKSCAN_CLEAR = single_write(7923, 0x09, 0x00)
AFTER_READ_0X33 = RegisterRead(6629, 0x33, 0x3C)
AFTER_WRITE_0X02 = single_write(6631, 0x02, 0x58)
AFTER_WRITE_0X0A = single_write(6635, 0x0A, 0x48)
AFTER_READ_0X101 = RegisterRead(6643, STATUS_REGISTER, 0xF4)
MOTOR_POWER_OFF = single_write(6373, 0x02, 0x08)
# --lamp-as-captured: 0x03 = 0x30 as the 27-pair block of frame 6259 set it before move 1 (LAMPPWR and bit 5), and
# 0x03 = 0x00 as frame 77 of the open wrote it, so that the lamp is off again at the end.
LAMP_AS_CAPTURED = register_write(None, bytes([0x03, 0x30]), kind="lamp_write")
LAMP_OFF = single_write(77, 0x03, 0x00)
# --as-move-1
REGISTER_STATE_MOVE_1_WRITES = register_state_writes(REGISTER_STATE_MOVE_1)
REGISTER_33_BEFORE_MOVE_1 = register_33_write(6085, 0x1C)
TABLE_UPLOADS_MOVE_1 = (
    (buffer_header(6263, TABLE_ADDRESSES[0], len(SLOPE_TABLE_MOVE_1)), table_upload(6267, SLOPE_TABLE_MOVE_1),
     upload_status_read(6269)),
    (buffer_header(6271, TABLE_ADDRESSES[1], len(SLOPE_TABLE_MOVE_1)), table_upload(6275, SLOPE_TABLE_MOVE_1),
     upload_status_read(6277)))
START_MOVE_1 = single_write(6279, 0x0F, 0x01)
MOVE_1_READ_0X101 = RegisterRead(6327, STATUS_REGISTER, 0xF4)  # the last read of 0x101 in move 1

REQUEST_ERRORS = (usb.core.USBError, PermissionError, ShortTransferError, LinkByteError, UnexpectedAnswerError)


def wire_form(request: Request) -> tuple:
    """What reaches the device: everything but the kind, the frame and the captured answer."""
    return (request.endpoint, request.request_type, request.request, request.value, request.index, request.sent,
            request.length)


def permitted_register_33_writes(register_33_read: typing.Optional[int]) -> list:
    """The value last read from 0x33 with bit 5 set or cleared, nothing before the first read."""
    if register_33_read is None:
        return []
    return [register_33_write(0, register_33_read | REGISTER_33_MOVE_BIT),
            register_33_write(0, register_33_read & ~REGISTER_33_MOVE_BIT & 0xFF)]


def permitted_move_1_requests(plan: MovePlan) -> list:
    """Move 1 has no 0x02 = 0x58, no 0x0a write, no read-modify-write of 0x33, no BACKSCAN and no lone lamp-on."""
    return [LINK_CHECK, *REGISTER_STATE_MOVE_1_WRITES, AFE_WRITE, REGISTER_33_BEFORE_MOVE_1, move_1_block(plan.steps),
            *(request for upload in TABLE_UPLOADS_MOVE_1 for request in upload), START_MOVE_1, CUT_MOTOR_POWER,
            CUT_FEEDL, LAMP_OFF]


def permitted_requests(plan: MovePlan) -> list:
    if plan.as_move_1:
        return permitted_move_1_requests(plan)
    requests = [LINK_CHECK, *REGISTER_STATE_WRITES, AFE_WRITE, REGISTER_33_RESET, BEFORE_WRITE_0X02,
                BEFORE_WRITE_0X0A, feed_block(plan.steps), *(request for upload in TABLE_UPLOADS for request in upload),
                START, CUT_MOTOR_POWER, CUT_FEEDL, AFTER_WRITE_0X02, AFTER_WRITE_0X0A, MOTOR_POWER_OFF,
                *permitted_register_33_writes(plan.register_33_read)]
    requests += [BACKSCAN_SET, BACKSCAN_CLEAR] if plan.backscan else []
    return requests + ([LAMP_AS_CAPTURED, LAMP_OFF] if plan.lamp else [])


def check_allowed(request: Request, plan: MovePlan) -> None:
    """Raise unless the request, as it would go on the wire, is one this run may send. Order is not checked."""
    if wire_form(request) not in {wire_form(permitted) for permitted in permitted_requests(plan)}:
        raise PermissionError(f"refusing {describe(request)}: not a request of this move")


def check_written(written: int, request: Request) -> bytes:
    if written != len(request.sent):
        raise ShortTransferError(f"{describe(request)}: sent {written} of {len(request.sent)} bytes")
    return b""


def send_on_wire(session: Session, request: Request) -> bytes:
    """The request's transfer. Return the answer of a read, b"" for a write."""
    if request.endpoint == BULK_OUT_ENDPOINT:
        return check_written(session.device.write(BULK_OUT_ENDPOINT, request.sent, TIMEOUT_MILLISECONDS), request)
    if request.request_type == VENDOR_IN:
        return control_in(session, request.request, request.value, request.index, request.length)
    written = session.device.ctrl_transfer(VENDOR_OUT, request.request, request.value, request.index, request.sent,
                                           TIMEOUT_MILLISECONDS)
    return check_written(written, request)


def transfer(session: Session, plan: MovePlan, request: Request) -> bytes:
    check_allowed(request, plan)
    try:
        return send_on_wire(session, request)
    except (usb.core.USBError, ShortTransferError) as error:
        raise StoppedAt(request.kind, request.frame) from error


def read_register(session: Session, register: int, kind: str, frame: typing.Optional[int]) -> int:
    """vendor_open.read_register (framing, 0x55 check) for the registers of LOGGED_REGISTERS only."""
    if register not in LOGGED_REGISTERS:
        raise PermissionError(f"refusing read of register 0x{register:02x}")
    try:
        return vendor_open.read_register(session, register)
    except (usb.core.USBError, ShortTransferError) as error:
        raise StoppedAt(kind, frame) from error


def read_captured_register(session: Session, read: RegisterRead) -> int:
    value = read_register(session, read.register, "register_read", read.frame)
    log(session, {"kind": "register_read", "frame": read.frame, "register": f"0x{read.register:02x}",
                  "received": f"{value:02x}", "captured": f"{read.captured:02x}", "differs": value != read.captured})
    return value


def read_logged_registers(session: Session, kind: str) -> dict:
    values = {register: read_register(session, register, kind, None) for register in LOGGED_REGISTERS}
    log(session, {"kind": kind, **{f"0x{register:02x}": f"{value:02x}" for register, value in values.items()}})
    return values


def request_log_record(request: Request, received: bytes) -> dict:
    entry = {"kind": request.kind, "frame": request.frame}
    if request.endpoint == BULK_OUT_ENDPOINT:
        return {**entry, "endpoint": f"{request.endpoint:02x}", "length": len(request.sent),
                "sha256": hashlib.sha256(request.sent).hexdigest()}
    entry.update({"request_type": f"{request.request_type:02x}", "request": f"{request.request:02x}",
                  "value": f"{request.value:04x}", "index": f"{request.index:04x}"})
    if request.request_type == VENDOR_OUT:
        return {**entry, "sent": request.sent.hex(" ")}
    return {**entry, "received": received.hex(" "), "captured": request.captured.hex(" "),
            "differs": received != request.captured}


def send_write(session: Session, plan: MovePlan, request: Request) -> None:
    """An OUT request, logged, then the link check that follows every write in the capture."""
    transfer(session, plan, request)
    log(session, request_log_record(request, b""))
    received = transfer(session, plan, LINK_CHECK)
    log(session, {"kind": "link_check", "after_frame": request.frame, "after": request.kind,
                  "received": received.hex()})
    require_link_byte(received[0], f"link check after {describe(request)}")


def send_table(session: Session, plan: MovePlan, request: Request) -> None:
    transfer(session, plan, request)
    log(session, request_log_record(request, b""))


def read_upload_status(session: Session, plan: MovePlan, request: Request) -> None:
    received = transfer(session, plan, request)
    log(session, request_log_record(request, received))
    if received != UPLOAD_STATUS_ANSWER:
        raise UnexpectedAnswerError(f"{describe(request)}: 0x{received.hex()}, expected 0x02")


def gate_refusal_reasons(registers: dict) -> list:
    """Why the registers read before the move do not show a finished open with the motor idle."""
    status = registers[STATUS_REGISTER]
    checks = ((status & PWRBIT, "PWRBIT clear: no open since the wake"),
              (not status & MOTORENB_BIT, "MOTORENB set: the motor is enabled"),
              (registers[GPIO_OUTPUT_ENABLE_REGISTER] == OPEN_GPIO_OUTPUT_ENABLE,
               "0x36 is not 0xfe: the open did not reach frame 115"))
    return [reason for passed, reason in checks if not passed]


def set_register_state(session: Session, plan: MovePlan) -> None:
    for request in (*REGISTER_STATE_WRITES, AFE_WRITE):
        send_write(session, plan, request)
    if plan.lamp:
        send_write(session, plan, LAMP_AS_CAPTURED)


def prepare_move(session: Session, plan: MovePlan) -> None:
    """Frames 6445 to 6466: 0x33 = 0x1c, bit 5 set by read-modify-write, then the block with FEEDL."""
    send_write(session, plan, REGISTER_33_RESET)
    plan.register_33_read = read_captured_register(session, BEFORE_READ_0X33)
    send_write(session, plan, BEFORE_WRITE_0X02)
    send_write(session, plan, BEFORE_WRITE_0X0A)
    send_write(session, plan, register_33_write(6459, plan.register_33_read | REGISTER_33_MOVE_BIT))
    if plan.backscan:
        send_write(session, plan, BACKSCAN_SET)
    send_write(session, plan, feed_block(plan.steps))


def upload_tables(session: Session, plan: MovePlan, uploads: tuple) -> None:
    """The same table to 0x1000c000 and 0x10010000 (frames 6467 to 6482, or 6263 to 6278 for move 1)."""
    for header, upload, status in uploads:
        send_write(session, plan, header)
        send_table(session, plan, upload)
        read_upload_status(session, plan, status)


def poll_log_record(window: PollWindow, now: float, status: int) -> dict:
    return {"kind": "poll", "phase": window.phase, "seconds_since_start": round(now - window.move_start, 4),
            "0x101": f"{status:02x}", "homesnr": bool(status & HOMESNR_BIT), "motorenb": bool(status & MOTORENB_BIT)}


def poll_until_motor_stops(session: Session, environment: Environment, window: PollWindow) -> bool:
    """Read 0x101 on the window's grid. True when MOTORENB clears, False when the window's limit has passed."""
    poll_number = 0
    while True:
        wait_until(environment, window.first_poll + poll_number * POLL_INTERVAL_SECONDS)
        now = environment.monotonic()
        status = read_register(session, STATUS_REGISTER, f"poll_{window.phase}", None)
        log(session, poll_log_record(window, now, status))
        if not status & MOTORENB_BIT:
            return True
        if now - window.first_poll >= window.limit_seconds:
            return False
        poll_number += 1


def cut_move(session: Session, environment: Environment, plan: MovePlan, move_start: float) -> bool:
    """Frames 6287 and 6291, the vendor's cut of moves 1 and 2, then polls until MOTORENB clears."""
    send_write(session, plan, CUT_MOTOR_POWER)
    send_write(session, plan, CUT_FEEDL)
    window = PollWindow("after_cut", move_start, environment.monotonic(), AFTER_CUT_POLL_LIMIT_SECONDS)
    return poll_until_motor_stops(session, environment, window)


def finish_move(session: Session, plan: MovePlan) -> None:
    """Frames 6629 to 6644 (with BACKSCAN cleared first as at 7923), then MTRPWR cleared."""
    if plan.backscan:
        send_write(session, plan, BACKSCAN_CLEAR)
    plan.register_33_read = read_captured_register(session, AFTER_READ_0X33)
    send_write(session, plan, AFTER_WRITE_0X02)
    send_write(session, plan, AFTER_WRITE_0X0A)
    send_write(session, plan, register_33_write(6639, plan.register_33_read & ~REGISTER_33_MOVE_BIT & 0xFF))
    read_captured_register(session, AFTER_READ_0X101)
    send_write(session, plan, MOTOR_POWER_OFF)
    if plan.lamp:
        send_write(session, plan, LAMP_OFF)


def finish_move_1(session: Session, plan: MovePlan) -> None:
    """MTRPWR cleared as by the vendor's cut (frame 6287), the lamp off, 0x101 read. Nothing that sets up move 2."""
    send_write(session, plan, CUT_MOTOR_POWER)
    send_write(session, plan, LAMP_OFF)
    read_captured_register(session, MOVE_1_READ_0X101)


def run_motor(session: Session, environment: Environment, plan: MovePlan, start: Request,
              poll_limit_seconds: float) -> bool:
    """The start write and the polls, with the cut when the limit passes. True when MOTORENB cleared in time."""
    move_start = environment.monotonic()
    send_write(session, plan, start)
    stopped = poll_until_motor_stops(session, environment,
                                     PollWindow("move", move_start, move_start, poll_limit_seconds))
    cleared_after_cut = None if stopped else cut_move(session, environment, plan, move_start)
    log(session, {"kind": "move_end", "motorenb_cleared_within_limit": stopped, "cut_sent": not stopped,
                  "motorenb_cleared_after_cut": cleared_after_cut,
                  "seconds_since_start": round(environment.monotonic() - move_start, 4)})
    return stopped


def move(session: Session, environment: Environment, plan: MovePlan, poll_limit_seconds: float) -> int:
    before = read_logged_registers(session, "registers_before")
    reasons = gate_refusal_reasons(before)
    if reasons:
        log(session, {"kind": "refused", "0x101": f"{before[STATUS_REGISTER]:02x}",
                      "0x36": f"{before[GPIO_OUTPUT_ENABLE_REGISTER]:02x}", "reason": ", ".join(reasons)})
        return EXIT_OPEN_NOT_SENT
    stopped = (move_1(session, environment, plan, poll_limit_seconds) if plan.as_move_1
               else move_3(session, environment, plan, poll_limit_seconds))
    read_logged_registers(session, "registers_after")
    return EXIT_GOOD if stopped else EXIT_MOTOR_TIMEOUT


def move_3(session: Session, environment: Environment, plan: MovePlan, poll_limit_seconds: float) -> bool:
    """Steps 3 to 7 for move 3. True when MOTORENB cleared within the limit."""
    set_register_state(session, plan)
    prepare_move(session, plan)
    upload_tables(session, plan, TABLE_UPLOADS)
    stopped = run_motor(session, environment, plan, START, poll_limit_seconds)
    finish_move(session, plan)
    return stopped


def move_1(session: Session, environment: Environment, plan: MovePlan, poll_limit_seconds: float) -> bool:
    """Steps 3 to 7 for move 1, frames 6259 to 6283 with the state and 0x33 they start from."""
    for request in (*REGISTER_STATE_MOVE_1_WRITES, AFE_WRITE, REGISTER_33_BEFORE_MOVE_1, move_1_block(plan.steps)):
        send_write(session, plan, request)
    upload_tables(session, plan, TABLE_UPLOADS_MOVE_1)
    stopped = run_motor(session, environment, plan, START_MOVE_1, poll_limit_seconds)
    finish_move_1(session, plan)
    return stopped


def tables_match_hash(uploads: tuple, table_sha256: str) -> bool:
    """The payloads the run would send, each against the SHA-256 of its table."""
    return all(hashlib.sha256(upload.sent).hexdigest() == table_sha256 for _, upload, _ in uploads)


def run(session: Session, environment: Environment, steps: int = DEFAULT_STEPS, backscan: bool = False,
        poll_limit_seconds: float = DEFAULT_POLL_LIMIT_SECONDS, lamp: bool = False, as_move_1: bool = False) -> int:
    """move() after the table check, with errors logged and mapped to an exit code."""
    uploads, table_sha256 = ((TABLE_UPLOADS_MOVE_1, SLOPE_TABLE_MOVE_1_SHA256) if as_move_1
                             else (TABLE_UPLOADS, SLOPE_TABLE_SHA256))
    if not tables_match_hash(uploads, table_sha256):
        log(session, {"kind": "refused", "reason": f"a table payload's SHA-256 is not {table_sha256}"})
        exit_code = EXIT_TABLE_HASH
    else:
        exit_code = move_with_errors_logged(session, environment, MovePlan(steps, backscan, lamp, as_move_1),
                                            poll_limit_seconds)
    log(session, {"kind": "exit", "code": exit_code})
    return exit_code


def move_with_errors_logged(session: Session, environment: Environment, plan: MovePlan,
                            poll_limit_seconds: float) -> int:
    try:
        return move(session, environment, plan, poll_limit_seconds)
    except StoppedAt as stop:
        log(session, {"kind": "error", "frame": stop.frame, "request": stop.kind, "error": str(stop.__cause__)})
    except REQUEST_ERRORS as error:
        log(session, {"kind": "error", "error": str(error)})
    return EXIT_USB_ERROR


def parent_pid(proc_root: pathlib.Path, pid: int) -> int:
    """The parent process from /proc/PID/stat (the field after the state), 0 when it cannot be read."""
    try:
        stat = (proc_root / str(pid) / "stat").read_text()
    except OSError:
        return 0
    return int(stat.rsplit(")", 1)[1].split()[1])


def own_process_chain(proc_root: pathlib.Path, pid: int) -> set:
    """This process and its ancestors, whose command lines name move_carrier.py too (sudo, the shell)."""
    chain = set()
    while pid > 0 and pid not in chain:
        chain.add(pid)
        pid = parent_pid(proc_root, pid)
    return chain


def conflicting_tool_running(proc_root: pathlib.Path, own_pid: int) -> bool:
    """True when a process outside this one's chain has a scanner tool of CONFLICTING_TOOL_NAMES as argument."""
    own_chain = own_process_chain(proc_root, own_pid)
    for cmdline in proc_root.glob("[0-9]*/cmdline"):
        if int(cmdline.parent.name) in own_chain:
            continue
        try:
            arguments = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        if any(argument.endswith(CONFLICTING_TOOL_NAMES) for argument in arguments):
            return True
    return False


def refusal_exit_code(probe_disabled: pathlib.Path, proc_root: pathlib.Path, own_pid: int,
                      device) -> typing.Optional[int]:
    """The exit code that refuses the run, or None when it may start."""
    if conflicting_tool_running(proc_root, own_pid):
        return EXIT_PROBE_ACTIVE
    return vendor_open.refusal_exit_code(probe_disabled, proc_root, device)


def steps_argument(text: str) -> int:
    steps = int(text)
    if not 1 <= steps <= MAXIMUM_STEPS:
        raise argparse.ArgumentTypeError(f"steps must be 1 to {MAXIMUM_STEPS}")
    return steps


def poll_limit_argument(text: str) -> float:
    seconds = float(text)
    if not (math.isfinite(seconds) and seconds > 0):
        raise argparse.ArgumentTypeError("the poll limit must be a number of seconds above 0")
    return seconds


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move the film holder carrier once, as the vendor's move 3 "
                                                 "(or move 1 with --as-move-1).")
    parser.add_argument("log_directory", type=pathlib.Path)
    parser.add_argument("--steps", type=steps_argument, default=DEFAULT_STEPS,
                        help=f"FEEDL, 1 to {MAXIMUM_STEPS} (default {DEFAULT_STEPS}, as the vendor's move 3; "
                             "move 1 used 10158)")
    parser.add_argument("--backscan", action="store_true",
                        help="set 0x09 bit 3 (BACKSCAN) for the move and nothing else: move 3's registers and "
                             "table with the direction bit match no move in the capture, and the capture has no "
                             "BACKSCAN move that starts off the home sensor")
    parser.add_argument("--poll-limit-seconds", type=poll_limit_argument, default=DEFAULT_POLL_LIMIT_SECONDS,
                        help=f"cut the move after this long (default {DEFAULT_POLL_LIMIT_SECONDS:g})")
    parser.add_argument("--lamp-as-captured", dest="lamp", action="store_true",
                        help="also write 0x03 = 0x30 (lamp on) before the move, as the capture's move 3 ran, and "
                             "0x03 = 0x00 at the end, so that the register state matches the capture in full")
    parser.add_argument("--as-move-1", action="store_true",
                        help="replay the vendor's move 1 (frames 6259 to 6283, table slope-6267) instead of move 3, "
                             "with FEEDL from --steps. Its block switches the lamp on, and the run switches it off "
                             "at the end. Not with --backscan or --lamp-as-captured")
    return parser


def option_conflict(arguments: argparse.Namespace) -> typing.Optional[str]:
    """Why the options cannot go together, or None."""
    if arguments.as_move_1 and arguments.backscan:
        return "--as-move-1 with --backscan: the capture has no move 1 with BACKSCAN"
    if arguments.as_move_1 and arguments.lamp:
        return "--as-move-1 with --lamp-as-captured: the block of frame 6259 switches the lamp on itself"
    return None


def parse_arguments(argument_list: typing.Optional[list] = None) -> argparse.Namespace:
    parser = argument_parser()
    arguments = parser.parse_args(argument_list)
    conflict = option_conflict(arguments)
    if conflict is not None:
        parser.error(conflict)
    return arguments


def main() -> int:
    arguments = parse_arguments()
    probe_disabled = pathlib.Path(__file__).resolve().parent / "probe-disabled"
    device = find_scanner()
    refusal = refusal_exit_code(probe_disabled, pathlib.Path("/proc"), os.getpid(), device)
    if refusal is not None:
        messages = {EXIT_PROBE_ACTIVE: f"create {probe_disabled} and wait until no probe_readonly.py, "
                                       "keep_awake.py, vendor_open.py, flash_dump.py, eeprom_read.py, snapshot.py "
                                       "or other move_carrier.py process runs",
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
                      "steps": arguments.steps, "backscan": arguments.backscan,
                      "poll_limit_seconds": arguments.poll_limit_seconds, "lamp": arguments.lamp,
                      "as_move_1": arguments.as_move_1})
        return run(session, Environment(), arguments.steps, arguments.backscan, arguments.poll_limit_seconds,
                   arguments.lamp, arguments.as_move_1)


if __name__ == "__main__":
    sys.exit(main())
