# Carrier moves in the issue #151 capture

How the working OpticFilm 120 in the SANE issue #151 capture moves its film holder carrier, byte for byte: every request of the seven move sequences, the register state the 97-step move starts from, the status values the driver polled until each move ended, and the slope tables. The purpose is a tool that replays one bounded move on the owner's unit with nothing invented (`../work/0011-first-motor-move.md`).

The capture, its phases and the request framing are described in `of120-capture-151.md`, and its conventions apply here: frame numbers as Wireshark numbers them, times in seconds since frame 1, *(inference)* on interpretations. Everything below that is not marked as inference was read from the capture with the commands at the end.

Sources:

- Capture: `work/downloads/gitlab-sane-project/issue-151-optifilm120-usb-capture/Optifilm120` (untracked), SHA-256 `6d14a09844a1859405d048c9020f9bf4b7192ba53373cb292ab836099fce01fc`, checked 2026-10-15.
- Tables are generated from `tools/usbpcap/decode.py --full-data` output, with requests paired and classified by `tools/usbpcap/annotate_gl128.py`.
- Names, cited as [tag line]: [G] SANE `backend/genesys/gl124_registers.h`, [H] `gl124.cpp`, [T] `gl124.h`, [R] `gl128_registers.h`, [L] `low.cpp`, [N] `genesys.cpp`, all in the checkout `work/downloads/sane-project/sane-backends-git` at commit `a8676a6`. [M] is the field map from Plustek's engine in `gl128-registers.md`. pyopticfilm is the submodule `pyopticfilm/` at commit `32dc576`, cited by file and line. GL124 names are applied to the GL128 by analogy *(inference)*, as in the walkthrough.

## Request framing

| Request | Wire form | Payload |
|---|---|---|
| Register write | `40 04 0083`, wIndex 0, wLength 2 per pair | address and value pairs, in the order the tables list them |
| Register write, `0x100` and up | `40 04 0183`, wIndex 0 | low address byte and value |
| Register read | `c0 04 008e` (`018e` for `0x100` and up), wIndex high byte = low address byte, low byte `0x22`, wLength 2 | value, then `0x55` |
| Link check | `c0 0c 008e`, wIndex `0x20`, wLength 1 | `0x55` |
| One-byte read at wIndex `0x18` | `c0 0c 008e`, wIndex `0x18`, wLength 1 | `0x02` after every table upload |
| Buffer header (write) | `40 04 0082`, wIndex `0x01`, wLength 8 | address and size, both 32-bit little endian |
| Table | bulk OUT endpoint `0x02` | 512 bytes |
| Interrupt read | interrupt IN endpoint `0x83` | one byte |

In the listings below, "Link check" names the link check that follows a request, with its frames. Runs of identical register reads are folded into one row with a count. The time column then gives the first and last submit. Every register read in the seven sequences returned `0x55` as its second byte, every link check `0x55`, every one-byte read at wIndex `0x18` `0x02`. Table payloads are named after the file in `tables/` that holds them (`tables/README.md`).

## Overview

The capture has 40 start writes (`0x0f = 0x01`). The 28 in the calibration rounds run with `0x02 = 0x00` (MTRPWR clear), the two image scans with `0x02 = 0x30`, and ten carrier moves with `0x02 = 0x18`, each after a register set-up and a pair of identical 512-byte tables to `0x1000c000` and `0x10010000`. Six of the ten are listed here: the four positioning moves of the first cycle, the move with BACKSCAN between the two passes, and the move at the end of the capture. The second cycle (frames 13725 to 14996) repeats the first cycle's positioning requests with the same tables, except that its fourth move is 37449 steps instead of 5592 (block at 14139, start at 14159, `0xd5` ×408 and `0xf5` ×8, `0xf4` at frame 14995), the second frame of the strip. Its move-3 register state differs from the first cycle's only in STRPIXEL and ENDPIXEL (`0x83`, `0x84`, `0x86`, `0x87`).

Times are seconds after the submit of the start write.

| Move | Frames | Start | FEEDL (`0x3d`-`0x3f`) | `0x09` | `0x33` | `0xae`-`0xaf` | Table | End of the move | FEEDFSH first seen | MOTORENB first seen clear |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 6257-6344 | 6279 | `0x0027ae` (10158) | `0x00` | `0x1c` | `0x007f` | `slope-6267` | interrupt `0x40` after 3.9050 s, then `0x02 = 0x08` and FEEDL 1 | 3.9066 | 4.1002 |
| 2 | 6345-6444 | 6365 | `0x0003d4` (980) | `0x00` | `0x3c` | `0x007f` | `slope-6353` | interrupt `0x20` after 1.2606 s, then `0x02 = 0x08` and FEEDL 1 | 1.2714 | 1.6164 |
| 3 | 6445-6644 | 6483 | `0x000061` (97) | `0x00` | `0x3c` | `0x00ff` | `slope-6353` | polling `0x101` only | 0.5853 | 1.0861 |
| 4 | 6645-6820 | 6665 | `0x0015d8` (5592) | `0x00` | `0x1c` | `0x00ff` | `slope-6653` | polling `0x101` only | 1.0390 | 1.1640 |
| Reverse | 7353-7940 | 7431 | `0x000880` (2176) | `0x08` | `0x3c` | `0x007f` | `slope-7419` | polling `0x101` only | 3.4581 | 3.8030 |
| Exit | 15533-15878 | 15585 | `0x0003c1` (961) | `0x08` | `0x3e` | `0x007f` | `slope-6353` | polling `0x101` only | 1.7098 | 2.0535 |

Motor related registers at each start write, from a replay of every register write since frame 15. Every move starts with `0x02 = 0x18` (MTRPWR and FASTFED [G 47-48]), `0x01 = 0x22`, `0x0a = 0x48`, `0x1c = 0x00` (TBTIME [G 162]), LPERIOD's top byte `0x7d = 0x00`, FWDSTEP and BWDSTEP `0x0080` (`0xa6`-`0xa9`, [G 277-278]), FSHDEC `0x0001` (`0xac`-`0xad`, [G 280]) and SCANFED `0x0000` (`0xa2`-`0xa3`, [G 275]). FMOVDEC (`0xb0`-`0xb1`, [G 282]) is never written in the capture. The rest:

| Register | Name | Move 1 | Move 2 | Move 3 | Move 4 | Reverse | Exit |
|---|---|---|---|---|---|---|---|
| `0x03` | lamp [G 53-58] | `0x30` | `0x30` | `0x30` | `0x30` | `0x30` | `0x00` |
| `0x04` | [G 60-64] | `0x42` | `0x42` | `0x42` | `0x42` | `0x02` | `0x42` |
| `0x05` | DPIHW and others [G 66-75] | `0xc8` | `0xc8` | `0xc8` | `0xc8` | `0xc8` | `0xc0` |
| `0x1d` | LINESEL and others [G 164-169] | `0x20` | `0x20` | `0x20` | `0x20` | `0x00` | `0x20` |
| `0x2c`-`0x2d` | DPISET [G 260] | `0x01e0` | `0x01e0` | `0x01e0` | `0x01e0` | `0x12c0` | `0x01e0` |
| `0x36` | GPIO output enable [M 126-130] | `0xfe` | `0xfe` | `0xfe` | `0xfe` | `0xfc` | `0xfe` |
| `0x7e`-`0x7f` | LPERIOD low bytes [G 265] | `0x9999` | `0x9999` | `0x9999` | `0x9999` | `0x7530` | `0x9999` |
| `0x81` | DUMMY low byte [G 266] | `0x11` | `0x11` | `0x11` | `0x11` | `0x22` | `0x11` |
| `0xa0` | FSTPSEL `0x38`, STEPSEL `0x07` [G 207-211] | `0x0a` | `0x0a` | `0x0a` | `0x0a` | `0x12` | `0x0a` |
| `0xa4`-`0xa5` | STEPNO [G 276] | `0x0026` | `0x0026` | `0x0026` | `0x0026` | `0x0020` | `0x0026` |
| `0xaa`-`0xab` | FASTNO [G 279] | `0x0026` | `0x0026` | `0x0026` | `0x0026` | `0x0030` | `0x0026` |

What the overview shows:

- Moves 3, 4 and the two moves with BACKSCAN end when the motor stops on its own: the driver polls `0x101` about every 16 ms until MOTORENB clears and writes nothing in between.
- Moves 1 and 2 end differently. The driver waits on the interrupt endpoint, and as soon as the byte arrives it writes `0x02 = 0x08` (MTRPWR cleared) and FEEDL `0x000001`, then polls. In move 2, the `0x101` read right after those writes (frame 6381) still shows FEEDFSH clear. FEEDFSH is set 9 ms later (frame 6383). The interrupt arrived 1.2606 s after the start of move 2 in the first cycle and 1.0195 s after the start of the same move in the second cycle (frames 13831 and 13838), while the first-seen times of move 3 agree within 5 ms between the cycles, with polls 15.6 ms apart (see "Move 3"). The exit move, 961 steps with the same table and the same FASTNO, STEPNO, FMOVNO, LPERIOD and `0xa0`, needed 1.7098 s to FEEDFSH. So move 2 ends on an event that the interrupt reports, before its 980 steps are done, and FEEDL 1 is how the driver cuts the feed short *(inference)*. Move 1 follows the same pattern, so its 10158 steps are probably an upper bound and not a blind distance *(inference, not decided by the capture)*.
- Move 3 is the only short move during which the driver writes nothing between the start and MOTORENB clearing, and no interrupt read is pending (the read of frame 6371 completed before the start, the next is submitted at 13725). Whether an event was held on the endpoint meanwhile the capture cannot show, so "runs to its programmed length" is an inference *(inference)*. It is the cleanest candidate for a replay. In the capture it always starts where move 2 stopped on its event, with the carrier off the home sensor.

## Move 1 (frames 6257 to 6344)

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 6257-6258 | 238.9454 | interrupt IN `0x83` | `0x04` |  |
| 6259-6260 | 238.9469 | register write (`40 04 0083`), 27 pairs | `0x03=0x30` `0x7d=0x00` `0x7e=0x99` `0x7f=0x99` `0x80=0x00` `0x81=0x11` `0x82=0x00` `0x83=0x02` `0x84=0x44` `0x85=0x00` `0x86=0x17` `0x87=0xac` `0x2c=0x01` `0x2d=0xe0` `0x04=0x42` `0x1d=0x20` `0x1c=0x00` `0xa4=0x00` `0xa5=0x26` `0xaa=0x00` `0xab=0x26` `0x02=0x18` `0xae=0x00` `0xaf=0x7f` `0x3d=0x00` `0x3e=0x27` `0x3f=0xae` | `0x55` (6261-6262) |
| 6263-6264 | 238.9481 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x1000c000`, size 512 (bytes `00 c0 00 10 00 02 00 00`) | `0x55` (6265-6266) |
| 6267-6268 | 238.9489 | bulk OUT `0x02`, 512 bytes | SHA-256 `47a4f0bc51c2a53ed0298d2b2e5e4bfdb0af3a40c5d812cacb470d2934b2d7a2` (`tables/slope-6267.hex`) |  |
| 6269-6270 | 238.9490 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6271-6272 | 238.9492 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x10010000`, size 512 (bytes `00 00 01 10 00 02 00 00`) | `0x55` (6273-6274) |
| 6275-6276 | 238.9500 | bulk OUT `0x02`, 512 bytes | SHA-256 `47a4f0bc51c2a53ed0298d2b2e5e4bfdb0af3a40c5d812cacb470d2934b2d7a2` (`tables/slope-6267.hex`) |  |
| 6277-6278 | 238.9500 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6279-6280 | 238.9503 | register write (`40 04 0083`) | `0x0f = 0x01` | `0x55` (6281-6282) |
| 6283-6284 | 238.9510 | register read `0x101` | `0xdd` |  |
| 6285-6286 | 238.9516 | interrupt IN `0x83` | `0x40` |  |
| 6287-6288 | 242.8555 | register write (`40 04 0083`) | `0x02 = 0x08` | `0x55` (6289-6290) |
| 6291-6292 | 242.8562 | register write (`40 04 0083`), 3 pairs | `0x3d=0x00` `0x3e=0x00` `0x3f=0x01` | `0x55` (6293-6294) |
| 6295-6320 | 242.8569 to 243.0345 | register read `0x101` | `0xf5` ×13 |  |
| 6321-6322 | 243.0505 | register read `0x101` | `0xf4` |  |
| 6323-6324 | 243.0665 | register write (`40 04 0083`) | `0x02 = 0x18` | `0x55` (6325-6326) |
| 6327-6328 | 243.0673 | register read `0x101` | `0xf4` |  |
| 6329-6330 | 243.0676 | register read `0x33` | `0x1c` |  |
| 6331-6332 | 243.0679 | register write (`40 04 0083`) | `0x02 = 0x58` | `0x55` (6333-6334) |
| 6335-6336 | 243.0686 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (6337-6338) |
| 6339-6340 | 243.0692 | register write (`40 04 0083`) | `0x33 = 0x3c` | `0x55` (6341-6342) |
| 6343-6344 | 243.0701 | interrupt IN `0x83` | no data, USBD status `0xc0010000` |  |

| Register | Value | Reads | Frames | First read (s after frame 6279) | Last read (s after frame 6279) |
|---|---|---|---|---|---|
| `0x101` | `0xdd` | 1 | 6283-6284 | 0.0007 | 0.0007 |
| `0x101` | `0xf5` | 13 | 6295-6320 | 3.9066 | 4.0842 |
| `0x101` | `0xf4` | 2 | 6321-6328 | 4.1002 | 4.1170 |

After the move: `0x02 = 0x18`, `0x02 = 0x58` (ACDCDIS, MTRPWR, FASTFED [G 45-48]), `0x0a = 0x48`, `0x33` read and written back with bit 5 set, then a new interrupt read that the driver cancels after 106 ms (USBD status `0xc0010000`, `USBD_STATUS_CANCELED`, see `of120-capture-151.md`, "Interrupt endpoint 0x83").

## Move 2 (frames 6345 to 6444)

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 6345-6346 | 243.1916 | register write (`40 04 0083`), 19 pairs | `0x3d=0x00` `0x3e=0x03` `0x3f=0xd4` `0x7d=0x00` `0x7e=0x99` `0x7f=0x99` `0x1c=0x00` `0x8a=0x00` `0x8b=0x55` `0x8c=0x00` `0x8d=0x00` `0x8e=0x55` `0x8f=0x00` `0x90=0x01` `0x91=0x54` `0x92=0x00` `0x02=0x18` `0xae=0x00` `0xaf=0x7f` | `0x55` (6347-6348) |
| 6349-6350 | 243.1928 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x1000c000`, size 512 (bytes `00 c0 00 10 00 02 00 00`) | `0x55` (6351-6352) |
| 6353-6354 | 243.1935 | bulk OUT `0x02`, 512 bytes | SHA-256 `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` (`tables/slope-6353.hex`) |  |
| 6355-6356 | 243.1936 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6357-6358 | 243.1939 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x10010000`, size 512 (bytes `00 00 01 10 00 02 00 00`) | `0x55` (6359-6360) |
| 6361-6362 | 243.1946 | bulk OUT `0x02`, 512 bytes | SHA-256 `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` (`tables/slope-6353.hex`) |  |
| 6363-6364 | 243.1946 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6365-6366 | 243.1949 | register write (`40 04 0083`) | `0x0f = 0x01` | `0x55` (6367-6368) |
| 6369-6370 | 243.1955 | register read `0x101` | `0xd5` |  |
| 6371-6372 | 243.1960 | interrupt IN `0x83` | `0x20` |  |
| 6373-6374 | 244.4557 | register write (`40 04 0083`) | `0x02 = 0x08` | `0x55` (6375-6376) |
| 6377-6378 | 244.4564 | register write (`40 04 0083`), 3 pairs | `0x3d=0x00` `0x3e=0x00` `0x3f=0x01` | `0x55` (6379-6380) |
| 6381-6382 | 244.4571 | register read `0x101` | `0xd5` |  |
| 6383-6426 | 244.4663 to 244.7953 | register read `0x101` | `0xf5` ×22 |  |
| 6427-6428 | 244.8113 | register read `0x101` | `0xf4` |  |
| 6429-6430 | 244.8272 | register write (`40 04 0083`) | `0x02 = 0x18` | `0x55` (6431-6432) |
| 6433-6434 | 244.8281 | register read `0x101` | `0xf4` |  |
| 6435-6436 | 244.8284 | register read `0x33` | `0x3c` |  |
| 6437-6438 | 244.8286 | register write (`40 04 0083`) | `0x02 = 0x58` | `0x55` (6439-6440) |
| 6441-6442 | 244.8294 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (6443-6444) |

| Register | Value | Reads | Frames | First read (s after frame 6365) | Last read (s after frame 6365) |
|---|---|---|---|---|---|
| `0x101` | `0xd5` | 2 | 6369-6382 | 0.0006 | 1.2622 |
| `0x101` | `0xf5` | 22 | 6383-6426 | 1.2714 | 1.6004 |
| `0x101` | `0xf4` | 2 | 6427-6434 | 1.6164 | 1.6332 |

The register block at frame 6345 lists FEEDL first and `0x1c` after LPERIOD. Moves 3 and 4 send the same 19 registers with `0x1c` first.

## Move 3, the 97-step move (frames 6445 to 6644)

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 6445-6446 | 244.8300 | register write (`40 04 0083`) | `0x33 = 0x1c` | `0x55` (6447-6448) |
| 6449-6450 | 244.8307 | register read `0x33` | `0x1c` |  |
| 6451-6452 | 244.8310 | register write (`40 04 0083`) | `0x02 = 0x58` | `0x55` (6453-6454) |
| 6455-6456 | 244.8317 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (6457-6458) |
| 6459-6460 | 244.8324 | register write (`40 04 0083`) | `0x33 = 0x3c` | `0x55` (6461-6462) |
| 6463-6464 | 244.8331 | register write (`40 04 0083`), 19 pairs | `0x1c=0x00` `0x3d=0x00` `0x3e=0x00` `0x3f=0x61` `0x7d=0x00` `0x7e=0x99` `0x7f=0x99` `0x8a=0x00` `0x8b=0x55` `0x8c=0x00` `0x8d=0x00` `0x8e=0x55` `0x8f=0x00` `0x90=0x01` `0x91=0x54` `0x92=0x00` `0x02=0x18` `0xae=0x00` `0xaf=0xff` | `0x55` (6465-6466) |
| 6467-6468 | 244.8342 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x1000c000`, size 512 (bytes `00 c0 00 10 00 02 00 00`) | `0x55` (6469-6470) |
| 6471-6472 | 244.8349 | bulk OUT `0x02`, 512 bytes | SHA-256 `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` (`tables/slope-6353.hex`) |  |
| 6473-6474 | 244.8350 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6475-6476 | 244.8353 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x10010000`, size 512 (bytes `00 00 01 10 00 02 00 00`) | `0x55` (6477-6478) |
| 6479-6480 | 244.8360 | bulk OUT `0x02`, 512 bytes | SHA-256 `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` (`tables/slope-6353.hex`) |  |
| 6481-6482 | 244.8360 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6483-6484 | 244.8364 | register write (`40 04 0083`) | `0x0f = 0x01` | `0x55` (6485-6486) |
| 6487-6562 | 244.8370 to 245.4060 | register read `0x101` | `0xd5` ×38 |  |
| 6563-6626 | 245.4217 to 245.9068 | register read `0x101` | `0xf5` ×32 |  |
| 6627-6628 | 245.9225 | register read `0x101` | `0xf4` |  |
| 6629-6630 | 245.9381 | register read `0x33` | `0x3c` |  |
| 6631-6632 | 245.9385 | register write (`40 04 0083`) | `0x02 = 0x58` | `0x55` (6633-6634) |
| 6635-6636 | 245.9393 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (6637-6638) |
| 6639-6640 | 245.9399 | register write (`40 04 0083`) | `0x33 = 0x1c` | `0x55` (6641-6642) |
| 6643-6644 | 245.9433 | register read `0x101` | `0xf4` |  |

| Register | Value | Reads | Frames | First read (s after frame 6483) | Last read (s after frame 6483) |
|---|---|---|---|---|---|
| `0x101` | `0xd5` | 38 | 6487-6562 | 0.0006 | 0.5697 |
| `0x101` | `0xf5` | 32 | 6563-6626 | 0.5853 | 1.0704 |
| `0x101` | `0xf4` | 2 | 6627-6644 | 1.0861 | 1.1070 |

The second cycle sends the same requests for its third move (frames 13909 to 14138, start write at 13947, same register block and table, 47 reads of `0xf5` instead of 32 because it polled faster for a while) and reads FEEDFSH first at 0.5850 s and MOTORENB clear first at 1.0818 s after the start, against 0.5853 s and 1.0861 s here.

After the move the driver writes `0x02 = 0x58`, rewrites `0x0a = 0x48`, clears bit 5 of `0x33` and goes straight on to move 4. It does not write `0x02 = 0x08` after move 3 or move 4, so MTRPWR stays set until the next move. MTRPWR is cleared in the capture only during calibration (`0x02 = 0x00`) and right after the interrupt of moves 1 and 2. At the end of the capture `0x02` is `0x18` (frame 15861).

### Register state at the start of move 3

Every register write (`40 04 0083` and `40 04 0183`) from frame 15 to frame 6483 replayed into a shadow, in submit order: 171 registers, 75 with the same value as in the open blast, 43 with a different value, 53 not in the blast. "Last written" is the first frame of the write transfer. The column on the right marks the registers of the 19-pair block at frame 6463.

| Register | Value | Open blast (17-36) | Differs from blast | Last written (frame) | In the block at 6463 |
|---|---|---|---|---|---|
| `0x01` | `0x22` | `0x22` | no | 6019 |  |
| `0x02` | `0x18` | `0x78` | yes | 6463 | yes, was `0x58` |
| `0x03` | `0x30` | `0x20` | yes | 6259 |  |
| `0x04` | `0x42` | `0x02` | yes | 6259 |  |
| `0x05` | `0xc8` | `0xc8` | no | 6019 |  |
| `0x06` | `0x18` | `0x18` | no | 6019 |  |
| `0x07` | `0x00` | `0x00` | no | 6019 |  |
| `0x08` | `0x80` | `0x80` | no | 6019 |  |
| `0x09` | `0x00` | `0x00` | no | 6019 |  |
| `0x0a` | `0x48` | `0x48` | no | 6455 |  |
| `0x0b` | `0x6c` | `0x6c` | no | 6019 |  |
| `0x0c` | `0x00` | `0x00` | no | 6019 |  |
| `0x0d` | `0x00` | `0x00` | no | 6019 |  |
| `0x0f` | `0x01` | not written | not in blast | 6483 |  |
| `0x11` | `0x00` | `0x00` | no | 6019 |  |
| `0x12` | `0x04` | `0x04` | no | 6019 |  |
| `0x13` | `0x08` | `0x08` | no | 6019 |  |
| `0x14` | `0x01` | `0x01` | no | 6019 |  |
| `0x15` | `0x80` | `0x80` | no | 6019 |  |
| `0x16` | `0xb7` | `0x01` | yes | 6019 |  |
| `0x17` | `0x0c` | `0x0c` | no | 6019 |  |
| `0x18` | `0x40` | `0x14` | yes | 6019 |  |
| `0x19` | `0x00` | `0x00` | no | 6019 |  |
| `0x1a` | `0x00` | `0x00` | no | 6019 |  |
| `0x1b` | `0x00` | `0x00` | no | 6019 |  |
| `0x1c` | `0x00` | `0x00` | no | 6463 | yes, same value |
| `0x1d` | `0x20` | `0x00` | yes | 6259 |  |
| `0x1e` | `0x10` | `0x10` | no | 6023 |  |
| `0x1f` | `0x00` | `0x00` | no | 6023 |  |
| `0x20` | `0x05` | `0x0c` | yes | 6023 |  |
| `0x21` | `0x00` | `0x00` | no | 6023 |  |
| `0x22` | `0x06` | `0x1a` | yes | 6023 |  |
| `0x23` | `0x00` | `0x00` | no | 6023 |  |
| `0x24` | `0x0f` | `0x1a` | yes | 6023 |  |
| `0x25` | `0x00` | `0x00` | no | 6023 |  |
| `0x26` | `0x00` | `0x00` | no | 6023 |  |
| `0x27` | `0x00` | `0x00` | no | 6023 |  |
| `0x28` | `0x00` | not written | not in blast | 5171 |  |
| `0x29` | `0x55` | not written | not in blast | 5171 |  |
| `0x2a` | `0x8a` | not written | not in blast | 5171 |  |
| `0x2b` | `0x20` | `0x20` | no | 6023 |  |
| `0x2c` | `0x01` | `0x12` | yes | 6259 |  |
| `0x2d` | `0xe0` | `0xc0` | yes | 6259 |  |
| `0x30` | `0x6f` | `0x6f` | no | 6023 |  |
| `0x31` | `0xfc` | `0xfc` | no | 6031 |  |
| `0x32` | `0x6b` | `0x6b` | no | 6023 |  |
| `0x33` | `0x3c` | `0x0e` | yes | 6459 |  |
| `0x34` | `0x80` | `0x80` | no | 6023 |  |
| `0x35` | `0x7f` | `0x7f` | no | 6023 |  |
| `0x36` | `0xfe` | `0xfc` | yes | 6079 |  |
| `0x37` | `0x32` | `0x30` | yes | 6023 |  |
| `0x38` | `0x77` | `0x77` | no | 6023 |  |
| `0x39` | `0x02` | `0x02` | no | 6023 |  |
| `0x3a` | `0x00` | `0x00` | no | 6023 |  |
| `0x3b` | `0xff` | `0xff` | no | 6023 |  |
| `0x3c` | `0xff` | `0xff` | no | 6023 |  |
| `0x3d` | `0x00` | `0x00` | no | 6463 | yes, same value |
| `0x3e` | `0x00` | `0x00` | no | 6463 | yes, same value |
| `0x3f` | `0x61` | `0x01` | yes | 6463 | yes, was `0x01` |
| `0x4f` | `0x03` | `0x03` | no | 6023 |  |
| `0x51` | `0x04` | not written | not in blast | 6175 |  |
| `0x52` | `0x08` | `0x07` | yes | 6023 |  |
| `0x53` | `0x0a` | `0x09` | yes | 6023 |  |
| `0x54` | `0x00` | `0x0b` | yes | 6023 |  |
| `0x55` | `0x02` | `0x01` | yes | 6023 |  |
| `0x56` | `0x04` | `0x03` | yes | 6023 |  |
| `0x57` | `0x06` | `0x05` | yes | 6023 |  |
| `0x58` | `0x07` | not written | not in blast | 6031 |  |
| `0x59` | `0x07` | not written | not in blast | 6031 |  |
| `0x5a` | `0x11` | `0x12` | yes | 6027 |  |
| `0x5b` | `0x49` | `0x00` | yes | 6027 |  |
| `0x5c` | `0x00` | `0x00` | no | 6027 |  |
| `0x5d` | `0x00` | not written | not in blast | 6175 |  |
| `0x5e` | `0x2a` | `0x1f` | yes | 6175 |  |
| `0x5f` | `0x00` | `0x01` | yes | 6027 |  |
| `0x60` | `0x00` | `0x00` | no | 6027 |  |
| `0x61` | `0x98` | `0x00` | yes | 6027 |  |
| `0x63` | `0x20` | `0x20` | no | 6027 |  |
| `0x67` | `0x7f` | `0x7f` | no | 6027 |  |
| `0x68` | `0x7f` | `0x7f` | no | 6027 |  |
| `0x69` | `0x01` | `0x01` | no | 6027 |  |
| `0x70` | `0x02` | `0x06` | yes | 6027 |  |
| `0x71` | `0x03` | `0x09` | yes | 6027 |  |
| `0x72` | `0x04` | `0x08` | yes | 6027 |  |
| `0x73` | `0x05` | `0x09` | yes | 6027 |  |
| `0x74` | `0x00` | `0x00` | no | 6027 |  |
| `0x75` | `0x00` | `0x00` | no | 6027 |  |
| `0x76` | `0x3f` | `0x00` | yes | 6027 |  |
| `0x77` | `0x00` | `0x00` | no | 6027 |  |
| `0x78` | `0x00` | `0x00` | no | 6027 |  |
| `0x79` | `0x3f` | `0x00` | yes | 6027 |  |
| `0x7a` | `0x00` | `0x00` | no | 6027 |  |
| `0x7b` | `0x00` | `0x00` | no | 6027 |  |
| `0x7c` | `0x3f` | `0x00` | yes | 6027 |  |
| `0x7d` | `0x00` | `0x00` | no | 6463 | yes, same value |
| `0x7e` | `0x99` | `0x75` | yes | 6463 | yes, same value |
| `0x7f` | `0x99` | `0x30` | yes | 6463 | yes, same value |
| `0x80` | `0x00` | `0x00` | no | 6259 |  |
| `0x81` | `0x11` | `0x22` | yes | 6259 |  |
| `0x82` | `0x00` | `0x00` | no | 6259 |  |
| `0x83` | `0x02` | `0x01` | yes | 6259 |  |
| `0x84` | `0x44` | `0x18` | yes | 6259 |  |
| `0x85` | `0x00` | `0x00` | no | 6259 |  |
| `0x86` | `0x17` | `0x00` | yes | 6259 |  |
| `0x87` | `0xac` | `0x00` | yes | 6259 |  |
| `0x88` | `0x00` | not written | not in blast | 6031 |  |
| `0x89` | `0x00` | not written | not in blast | 6031 |  |
| `0x8a` | `0x00` | not written | not in blast | 6463 | yes, same value |
| `0x8b` | `0x55` | not written | not in blast | 6463 | yes, same value |
| `0x8c` | `0x00` | not written | not in blast | 6463 | yes, same value |
| `0x8d` | `0x00` | not written | not in blast | 6463 | yes, same value |
| `0x8e` | `0x55` | not written | not in blast | 6463 | yes, same value |
| `0x8f` | `0x00` | not written | not in blast | 6463 | yes, same value |
| `0x90` | `0x01` | not written | not in blast | 6463 | yes, same value |
| `0x91` | `0x54` | not written | not in blast | 6463 | yes, same value |
| `0x92` | `0x00` | not written | not in blast | 6463 | yes, same value |
| `0x93` | `0x00` | `0x00` | no | 6031 |  |
| `0x94` | `0x00` | `0x00` | no | 6031 |  |
| `0x95` | `0x00` | `0x00` | no | 6031 |  |
| `0x9d` | `0x08` | `0x08` | no | 6031 |  |
| `0xa0` | `0x0a` | `0x12` | yes | 6031 |  |
| `0xa2` | `0x00` | not written | not in blast | 5167 |  |
| `0xa3` | `0x00` | not written | not in blast | 5167 |  |
| `0xa4` | `0x00` | `0x00` | no | 6259 |  |
| `0xa5` | `0x26` | `0x20` | yes | 6259 |  |
| `0xa6` | `0x00` | `0x00` | no | 6019 |  |
| `0xa7` | `0x80` | `0x80` | no | 6019 |  |
| `0xa8` | `0x00` | `0x00` | no | 6019 |  |
| `0xa9` | `0x80` | `0x80` | no | 6019 |  |
| `0xaa` | `0x00` | `0x00` | no | 6259 |  |
| `0xab` | `0x26` | `0x30` | yes | 6259 |  |
| `0xac` | `0x00` | not written | not in blast | 5167 |  |
| `0xad` | `0x01` | not written | not in blast | 5167 |  |
| `0xae` | `0x00` | not written | not in blast | 6463 | yes, same value |
| `0xaf` | `0xff` | not written | not in blast | 6463 | yes, was `0x7f` |
| `0xb8` | `0x00` | `0x00` | no | 6031 |  |
| `0xb9` | `0x38` | `0x38` | no | 6031 |  |
| `0xba` | `0x00` | `0x00` | no | 6031 |  |
| `0xbd` | `0x00` | `0x00` | no | 6031 |  |
| `0xbe` | `0x00` | `0x00` | no | 6031 |  |
| `0xbf` | `0x00` | `0x00` | no | 6031 |  |
| `0xd0` | `0x0a` | not written | not in blast | 6193 |  |
| `0xd1` | `0x0a` | not written | not in blast | 6197 |  |
| `0xd2` | `0x0a` | not written | not in blast | 6201 |  |
| `0xe0` | `0x00` | not written | not in blast | 6205 |  |
| `0xe1` | `0xc8` | not written | not in blast | 6205 |  |
| `0xe2` | `0x15` | not written | not in blast | 6209 |  |
| `0xe3` | `0xfb` | not written | not in blast | 6209 |  |
| `0xe4` | `0x15` | not written | not in blast | 6213 |  |
| `0xe5` | `0xfc` | not written | not in blast | 6213 |  |
| `0xe6` | `0x2b` | not written | not in blast | 6217 |  |
| `0xe7` | `0x2f` | not written | not in blast | 6217 |  |
| `0xe8` | `0x2b` | not written | not in blast | 6221 |  |
| `0xe9` | `0x30` | not written | not in blast | 6221 |  |
| `0xea` | `0x40` | not written | not in blast | 6225 |  |
| `0xeb` | `0x63` | not written | not in blast | 6225 |  |
| `0xec` | `0x40` | not written | not in blast | 6229 |  |
| `0xed` | `0x64` | not written | not in blast | 6229 |  |
| `0xee` | `0x55` | not written | not in blast | 6233 |  |
| `0xef` | `0x97` | not written | not in blast | 6233 |  |
| `0xf0` | `0x55` | not written | not in blast | 6237 |  |
| `0xf1` | `0x98` | not written | not in blast | 6237 |  |
| `0xf2` | `0x6a` | not written | not in blast | 6241 |  |
| `0xf3` | `0xcb` | not written | not in blast | 6241 |  |
| `0xf4` | `0x6a` | not written | not in blast | 6245 |  |
| `0xf5` | `0xcc` | not written | not in blast | 6245 |  |
| `0xf6` | `0x7f` | not written | not in blast | 6249 |  |
| `0xf7` | `0xff` | not written | not in blast | 6249 |  |
| `0xf8` | `0x05` | not written | not in blast | 6253 |  |
| `0x114` | `0x80` | `0x80` | no | 6039 |  |
| `0x115` | `0x80` | `0x80` | no | 6039 |  |

Notes on the table:

- `0x0d` (clear counters [G 126-131]) and `0x0f` (start) are commands, so their shadow value is only the last value written. `0x0f = 0x01` at frame 6483 is the start of move 3 itself.
- `0x51`, `0x5d` and `0x5e` carry the AFE writes (index, high and low byte, see the walkthrough's boot sequence), so their shadow value is the last AFE write (AFE register 4 = `0x002a` at frame 6175). `0x5e` is also in the blast with `0x1f`. In SANE's GL841 to GL847 headers `0x5e` holds the motor fields DECSEL and STOPTIM (`gl843_registers.h` lines 250 to 254); whether the GL128 uses it that way is not known, so a replay that sends the blast without the AFE writes starts move 3 with a different `0x5e` than the capture *(inference)*.
- The table is a replay of writes. For the GPIO registers a read returns pin levels, not the written value: `0x31` is `0xfc` here (written at 6031) but reads `0xbb` at frames 6005 and 7315, and `0x33` reads differ from the written values as well (the read-modify-write sequences in "What the capture does not show").
- `0x28` to `0x2a`, `0xa2`, `0xa3`, `0xac` and `0xad` were last written during the second calibration round (frames 5167 and 5171), not in the set-up blast at 6019.
- The write_0x8c requests (`40 0c 008c`, wIndex `0x10` and `0x13`, value `0x0d`, last at frames 6011 and 6015) are not register writes and are not in the table.

The block at frame 6463 (19 pairs, in wire order):

| Order | Register | Value | Name | Change |
|---|---|---|---|---|
| 1 | `0x1c` | `0x00` | TBTIME [G 162] | same value |
| 2 to 4 | `0x3d`-`0x3f` | `00 00 61` | FEEDL, 97 [G 261, M 155] | `0x3f` was `0x01` (FEEDL 1 from frame 6377) |
| 5 to 7 | `0x7d`-`0x7f` | `00 99 99` | LPERIOD [G 265, M 162] | same value |
| 8 to 10 | `0x8a`-`0x8c` | `00 55 00` | EXPR [G 270, M 167] | same value |
| 11 to 13 | `0x8d`-`0x8f` | `00 55 00` | EXPG [G 271, M 168] | same value |
| 14 to 16 | `0x90`-`0x92` | `01 54 00` | EXPB [G 272, M 169] | same value |
| 17 | `0x02` | `0x18` | MTRPWR, FASTFED [G 47-48] | was `0x58` (ACDCDIS cleared) |
| 18 to 19 | `0xae`-`0xaf` | `00 ff` | FMOVNO [G 281, M 181] | `0xaf` was `0x7f` |

So the block changes three registers against the state before it: `0x02` from `0x58` to `0x18`, FEEDL from 1 to 97, FMOVNO from 127 to 255. The other 16 values are rewritten unchanged. Everything else in the register state was set by earlier requests: the set-up blast at 6019 to 6042, the AFE and memory layout writes, the 27-pair block of move 1 at 6259 (lamp, LPERIOD, DUMMY, STRPIXEL, ENDPIXEL, DPISET, `0x04`, `0x1d`, STEPNO, FASTNO), `0x36 = 0xfe` at 6079, and the `0x33` write at 6459. What the move depends on beyond the registers the capture does not show: before 6483 there are also the bulk uploads at 6183 and 6185 (header `00 40 01 10 98 23 00 00`, the shading table), the write_0x8c requests at 6011 and 6015, and the boot-time `40 0c 008b` and `40 04 008b` requests at frames 57, 61 and 67.

## Move 4 (frames 6645 to 6820)

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 6645-6646 | 245.9437 | register write (`40 04 0083`), 19 pairs | `0x1c=0x00` `0x3d=0x00` `0x3e=0x15` `0x3f=0xd8` `0x7d=0x00` `0x7e=0x99` `0x7f=0x99` `0x8a=0x00` `0x8b=0x55` `0x8c=0x00` `0x8d=0x00` `0x8e=0x55` `0x8f=0x00` `0x90=0x01` `0x91=0x54` `0x92=0x00` `0x02=0x18` `0xae=0x00` `0xaf=0xff` | `0x55` (6647-6648) |
| 6649-6650 | 245.9448 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x1000c000`, size 512 (bytes `00 c0 00 10 00 02 00 00`) | `0x55` (6651-6652) |
| 6653-6654 | 245.9456 | bulk OUT `0x02`, 512 bytes | SHA-256 `838b1154f780d8d8550ae565bbb143170e0caa17acd8ceb35b9dceca45402c92` (`tables/slope-6653.hex`) |  |
| 6655-6656 | 245.9457 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6657-6658 | 245.9460 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x10010000`, size 512 (bytes `00 00 01 10 00 02 00 00`) | `0x55` (6659-6660) |
| 6661-6662 | 245.9467 | bulk OUT `0x02`, 512 bytes | SHA-256 `838b1154f780d8d8550ae565bbb143170e0caa17acd8ceb35b9dceca45402c92` (`tables/slope-6653.hex`) |  |
| 6663-6664 | 245.9468 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 6665-6666 | 245.9472 | register write (`40 04 0083`) | `0x0f = 0x01` | `0x55` (6667-6668) |
| 6669-6802 | 245.9479 to 246.9705 | register read `0x101` | `0xd5` ×67 |  |
| 6803-6818 | 246.9861 to 247.0955 | register read `0x101` | `0xf5` ×8 |  |
| 6819-6820 | 247.1111 | register read `0x101` | `0xf4` |  |

| Register | Value | Reads | Frames | First read (s after frame 6665) | Last read (s after frame 6665) |
|---|---|---|---|---|---|
| `0x101` | `0xd5` | 67 | 6669-6802 | 0.0008 | 1.0234 |
| `0x101` | `0xf5` | 8 | 6803-6818 | 1.0390 | 1.1484 |
| `0x101` | `0xf4` | 1 | 6819-6820 | 1.1640 | 1.1640 |

After move 4 the driver uploads the three tables to `0x10000000`, `0x10004000` and `0x10008000` (frames 6821 to 6844, see "Slope tables") and sets up image 1 with `0x02 = 0x30` (AGOHOME and MTRPWR [G 46-47]) at frame 6849.

## End of pass, the park (frames 7143 to 7314)

There is no start write, no table upload and no FEEDL write in this sequence. Image 1 was started at frame 6857 with `0x02 = 0x30` (AGOHOME, MTRPWR), set at frame 6849. The `0x101` reads during the image (frames 6861 to 7086) return `0xc5`, `0xe5` and `0xa5`, all with HOMESNR clear.

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 7143-7144 | 255.3631 | vendor request `40 0c 008d` wIndex `0x0000` wLength 1 | out `00` in `-` | `0x55` (7145-7146) |
| 7147-7148 | 255.3638 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 7149-7150 | 255.3642 | register read `0x101` | `0xd5` |  |
| 7151-7152 | 255.3645 | register write (`40 04 0083`) | `0x03 = 0x20` | `0x55` (7153-7154) |
| 7155-7156 | 255.3652 | register write (`40 04 0083`) | `0x01 = 0x22` | `0x55` (7157-7158) |
| 7159-7170 | 255.3659 to 255.4413 | register read `0x100` | `0x31` ×6 |  |
| 7171-7184 | 255.4569 to 255.5507 | register read `0x100` | `0x33` ×7 |  |
| 7185-7222 | 255.5666 to 255.8482 | register read `0x100` | `0x37` ×19 |  |
| 7223-7286 | 255.8795 to 256.3642 | register read `0x101` | `0xf1` ×32 |  |
| 7287-7288 | 256.3964 | register read `0x06` | `0x18` |  |
| 7289-7290 | 256.3968 | register write (`40 04 0083`) | `0x02 = 0x30` | `0x55` (7291-7292) |
| 7293-7294 | 256.3975 | register read `0x36` | `0xfe` |  |
| 7295-7296 | 256.3978 | register write (`40 04 0083`) | `0x36 = 0xfe` | `0x55` (7297-7298) |
| 7299-7300 | 256.3985 | register read `0x33` | `0x1c` |  |
| 7301-7302 | 256.3987 | register write (`40 04 0083`) | `0x33 = 0x1e` | `0x55` (7303-7304) |
| 7305-7306 | 256.3994 | register read `0x101` | `0xf1` |  |
| 7307-7308 | 256.3998 | register read `0x100` | `0x37` |  |
| 7309-7310 | 256.4000 | register read `0x33` | `0x1e` |  |
| 7311-7312 | 256.4004 | register write (`40 04 0083`) | `0x33 = 0x1e` | `0x55` (7313-7314) |

Status reads, times after `0x01 = 0x22` at frame 7155 (SCAN cleared [G 41]):

| Register | Value | Reads | Frames | First read (s after frame 7155) | Last read (s after frame 7155) |
|---|---|---|---|---|---|
| `0x101` | `0xd5` | 1 | 7149-7150 | -0.0010 | -0.0010 |
| `0x100` | `0x31` | 6 | 7159-7170 | 0.0007 | 0.0761 |
| `0x100` | `0x33` | 7 | 7171-7184 | 0.0917 | 0.1855 |
| `0x100` | `0x37` | 19 | 7185-7222 | 0.2014 | 0.4830 |
| `0x101` | `0xf1` | 33 | 7223-7306 | 0.5143 | 1.0342 |
| `0x100` | `0x37` | 1 | 7307-7308 | 1.0346 | 1.0346 |
| `0x101` | `0xf8` | 2 | 7353-7358 | 12.7926 | 12.7933 |

`0x100` bits with GL124 names [G 245-253]: `0x31` is COVERSNR, CHKVER and DATAENB, `0x33` adds MOTMFLG, `0x37` adds HISPDFLG. [M 194-198] confirms COVERSNR, DATAENB and MOTMFLG at those positions in Plustek's engine. SANE's GL128 backend treats `0x100` as absent on the GL128 (`gl128.cpp` lines 1353 to 1354, [N 647-651]). This capture reads changing values there.

The driver stops polling at 256.40 s with MOTORENB still set and HOMESNR clear (`0xf1`). Between frames 7315 and 7352 it reads only `0x31`. The next `0x101` read, at 268.16 s (frame 7353), returns `0xf8`: HOMESNR set, MOTORENB clear. So the carrier reached the home sensor at some point in those 11.8 s, driven by AGOHOME after the end of the scan *(inference: no other motor request is sent in between)*.

## Reverse move, with BACKSCAN, between the passes (frames 7353 to 7940)

The range runs to 7940, past 7928 in the walkthrough, so that it includes the last three writes after the move.

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 7353-7354 | 268.1578 | register read `0x101` | `0xf8` |  |
| 7355-7356 | 268.1582 | register read `0x31` | `0xbb` |  |
| 7357-7358 | 268.1585 | register read `0x101` | `0xf8` |  |
| 7359-7360 | 268.1589 | register read `0x36` | `0xfe` |  |
| 7361-7362 | 268.1591 | register write (`40 04 0083`) | `0x36 = 0xfe` | `0x55` (7363-7364) |
| 7365-7366 | 268.1599 | register read `0x33` | `0x1e` |  |
| 7367-7368 | 268.1601 | register write (`40 04 0083`) | `0x33 = 0x1c` | `0x55` (7369-7370) |
| 7371-7372 | 268.1608 | register read `0x101` | `0xf8` |  |
| 7373-7374 | 268.1611 | one-byte read (`c0 0c 008e` wIndex `0x00`) | `0x00` |  |
| 7375-7376 | 268.1677 | register read `0x101` | `0xf8` |  |
| 7377-7378 | 268.1681 | register read `0x33` | `0x1c` |  |
| 7379-7380 | 268.1684 | register write (`40 04 0083`) | `0x02 = 0x78` | `0x55` (7381-7382) |
| 7383-7384 | 268.1690 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (7385-7386) |
| 7387-7388 | 268.1697 | register write (`40 04 0083`) | `0x33 = 0x3c` | `0x55` (7389-7390) |
| 7391-7392 | 268.1704 | register write (`40 04 0083`) | `0x09 = 0x08` | `0x55` (7393-7394) |
| 7395-7396 | 268.1711 | register write (`40 04 0083`), 32 pairs | `0x01=0x22` `0x03=0x30` `0x04=0x02` `0x05=0xc8` `0x06=0x18` `0x07=0x00` `0x08=0x80` `0x0b=0x6c` `0x0c=0x00` `0x0d=0x00` `0x11=0x00` `0x12=0x04` `0x13=0x08` `0x14=0x01` `0x15=0x80` `0x16=0x01` `0x17=0x0c` `0x18=0x14` `0x19=0x00` `0x1a=0x00` `0x1b=0x00` `0x1c=0x00` `0x1d=0x00` `0x1e=0x10` `0x1f=0x00` `0x20=0x0c` `0x21=0x00` `0x22=0x1a` `0x23=0x00` `0x24=0x1a` `0x25=0x00` `0x26=0x00` | `0x55` (7397-7398) |
| 7399-7400 | 268.1722 | register write (`40 04 0083`), 32 pairs | `0x27=0x00` `0x2b=0x20` `0x2c=0x12` `0x2d=0xc0` `0x30=0x6f` `0x31=0xfc` `0x32=0x6b` `0x34=0x80` `0x35=0x7f` `0x37=0x30` `0x38=0x77` `0x39=0x02` `0x3a=0x00` `0x3b=0xff` `0x3c=0xff` `0x3d=0x00` `0x3e=0x08` `0x3f=0x80` `0x4f=0x03` `0x52=0x07` `0x53=0x09` `0x54=0x0b` `0x55=0x01` `0x56=0x03` `0x57=0x05` `0x5a=0x12` `0x5b=0x00` `0x5c=0x00` `0x5e=0x1f` `0x5f=0x01` `0x60=0x00` `0x61=0x00` | `0x55` (7401-7402) |
| 7403-7404 | 268.1734 | register write (`40 04 0083`), 32 pairs | `0x63=0x20` `0x67=0x7f` `0x68=0x7f` `0x69=0x01` `0x70=0x06` `0x71=0x09` `0x72=0x08` `0x73=0x09` `0x74=0x00` `0x75=0x00` `0x76=0x00` `0x77=0x00` `0x78=0x00` `0x79=0x00` `0x7a=0x00` `0x7b=0x00` `0x7c=0x00` `0x7d=0x00` `0x7e=0x75` `0x7f=0x30` `0x80=0x00` `0x81=0x22` `0x82=0x00` `0x83=0x01` `0x84=0x18` `0x85=0x00` `0x86=0x00` `0x87=0x00` `0x93=0x00` `0x94=0x00` `0x95=0x00` `0x9d=0x08` | `0x55` (7405-7406) |
| 7407-7408 | 268.1744 | register write (`40 04 0083`), 19 pairs | `0xa0=0x12` `0xa4=0x00` `0xa5=0x20` `0xa6=0x00` `0xa7=0x80` `0xa8=0x00` `0xa9=0x80` `0xaa=0x00` `0xab=0x30` `0xb8=0x00` `0xb9=0x38` `0xba=0x00` `0xbd=0x00` `0xbe=0x00` `0xbf=0x00` `0x36=0xfc` `0x02=0x18` `0xae=0x00` `0xaf=0x7f` | `0x55` (7409-7410) |
| 7411-7412 | 268.1753 | register write (`40 04 0183`), 2 pairs | `0x114=0x80` `0x115=0x80` | `0x55` (7413-7414) |
| 7415-7416 | 268.1762 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x1000c000`, size 512 (bytes `00 c0 00 10 00 02 00 00`) | `0x55` (7417-7418) |
| 7419-7420 | 268.1769 | bulk OUT `0x02`, 512 bytes | SHA-256 `a73cbf604e186370e5113abc8343bbd1f7a13ca4d3a94f22b31b798a8b537a76` (`tables/slope-7419.hex`) |  |
| 7421-7422 | 268.1770 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 7423-7424 | 268.1773 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x10010000`, size 512 (bytes `00 00 01 10 00 02 00 00`) | `0x55` (7425-7426) |
| 7427-7428 | 268.1780 | bulk OUT `0x02`, 512 bytes | SHA-256 `a73cbf604e186370e5113abc8343bbd1f7a13ca4d3a94f22b31b798a8b537a76` (`tables/slope-7419.hex`) |  |
| 7429-7430 | 268.1781 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 7431-7432 | 268.1783 | register write (`40 04 0083`) | `0x0f = 0x01` | `0x55` (7433-7434) |
| 7435-7876 | 268.1790 to 271.6208 | register read `0x101` | `0xdd` ×221 |  |
| 7877-7920 | 271.6364 to 271.9656 | register read `0x101` | `0xfd` ×22 |  |
| 7921-7922 | 271.9813 | register read `0x101` | `0xfc` |  |
| 7923-7924 | 271.9969 | register write (`40 04 0083`) | `0x09 = 0x00` | `0x55` (7925-7926) |
| 7927-7928 | 271.9977 | register read `0x33` | `0x3e` |  |
| 7929-7930 | 271.9980 | register write (`40 04 0083`) | `0x02 = 0x58` | `0x55` (7931-7932) |
| 7933-7934 | 271.9987 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (7935-7936) |
| 7937-7938 | 271.9994 | register write (`40 04 0083`) | `0x33 = 0x1e` | `0x55` (7939-7940) |

| Register | Value | Reads | Frames | First read (s after frame 7431) | Last read (s after frame 7431) |
|---|---|---|---|---|---|
| `0x101` | `0xdd` | 221 | 7435-7876 | 0.0007 | 3.4424 |
| `0x101` | `0xfd` | 22 | 7877-7920 | 3.4581 | 3.7873 |
| `0x101` | `0xfc` | 1 | 7921-7922 | 3.8030 | 3.8030 |

This is the only move that resends the open blast (frames 7395 to 7414). Against frames 17 to 36 the resent blast leaves out `0x09`, `0x0a` and `0x33` (written on their own just before), moves `0x36` (`0xfc` as at open) to the end of the last transfer, adds `0x02 = 0x18` and `0xae`-`0xaf = 0x007f` after it, and changes three values: `0x03 = 0x30`, FEEDL `0x000880` and `0x02`. BACKSCAN is set by its own write at frame 7391 and cleared at 7923, right after the motor stopped. `0x33` was written `0x3c` at 7387 and reads `0x3e` at 7927: bit 1 (GPIO18 [M 106], the bit of plist key `LoaderEjectSwitch` in `gl128-registers.md`) changed while `0x36` bit 1 was clear, that is while GPIO18 was not an output *(inference from the GPOE18 name [M 127])*.

## Exit move at the end of the capture (frames 15533 to 15878)

| Frames | Time (s) | Request | Value or result | Link check |
|---|---|---|---|---|
| 15533-15534 | 318.0040 | register write (`40 04 0083`) | `0x03 = 0x00` |  |
| 15535-15536 | 318.0044 | register write (`40 04 0083`) | `0x03 = 0x00` |  |
| 15537-15538 | 318.0048 | register read `0x31` | `0xbb` |  |
| 15539-15540 | 318.0051 | register write (`40 04 0083`) | `0x31 = 0x3b` | `0x55` (15541-15542) |
| 15543-15546 | 318.0058 to 318.0061 | register read `0x101` | `0xf8` ×2 |  |
| 15547-15548 | 318.0064 | register read `0x33` | `0x1e` |  |
| 15549-15550 | 318.0067 | register write (`40 04 0083`) | `0x02 = 0x30` | `0x55` (15551-15552) |
| 15553-15554 | 318.0074 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (15555-15556) |
| 15557-15558 | 318.0081 | register write (`40 04 0083`) | `0x33 = 0x3e` | `0x55` (15559-15560) |
| 15561-15562 | 318.0088 | register write (`40 04 0083`) | `0x09 = 0x08` | `0x55` (15563-15564) |
| 15565-15566 | 318.0094 | register write (`40 04 0083`), 6 pairs | `0x02=0x18` `0xae=0x00` `0xaf=0x7f` `0x3d=0x00` `0x3e=0x03` `0x3f=0xc1` | `0x55` (15567-15568) |
| 15569-15570 | 318.0104 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x1000c000`, size 512 (bytes `00 c0 00 10 00 02 00 00`) | `0x55` (15571-15572) |
| 15573-15574 | 318.0112 | bulk OUT `0x02`, 512 bytes | SHA-256 `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` (`tables/slope-6353.hex`) |  |
| 15575-15576 | 318.0113 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 15577-15578 | 318.0116 | buffer header (`40 04 0082` wIndex `0x01`) | address `0x10010000`, size 512 (bytes `00 00 01 10 00 02 00 00`) | `0x55` (15579-15580) |
| 15581-15582 | 318.0125 | bulk OUT `0x02`, 512 bytes | SHA-256 `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` (`tables/slope-6353.hex`) |  |
| 15583-15584 | 318.0125 | one-byte read (`c0 0c 008e` wIndex `0x18`) | `0x02` |  |
| 15585-15586 | 318.0128 | register write (`40 04 0083`) | `0x0f = 0x01` | `0x55` (15587-15588) |
| 15589-15808 | 318.0136 to 319.7070 | register read `0x101` | `0xd9` ×110 |  |
| 15809-15852 | 319.7226 to 320.0507 | register read `0x101` | `0xf9` ×22 |  |
| 15853-15854 | 320.0663 | register read `0x101` | `0xf8` |  |
| 15855-15856 | 320.0820 | register write (`40 04 0083`) | `0x09 = 0x00` | `0x55` (15857-15858) |
| 15859-15860 | 320.0828 | register read `0x33` | `0x3e` |  |
| 15861-15862 | 320.0831 | register write (`40 04 0083`) | `0x02 = 0x18` | `0x55` (15863-15864) |
| 15865-15866 | 320.0839 | register write (`40 04 0083`) | `0x0a = 0x48` | `0x55` (15867-15868) |
| 15869-15870 | 320.0847 | register write (`40 04 0083`) | `0x33 = 0x1e` | `0x55` (15871-15872) |
| 15873-15874 | 320.2785 | register read `0x31` | `0x3b` |  |
| 15875-15876 | 320.2789 | register write (`40 04 0083`) | `0x31 = 0x3b` | `0x55` (15877-15878) |

| Register | Value | Reads | Frames | First read (s after frame 15585) | Last read (s after frame 15585) |
|---|---|---|---|---|---|
| `0x101` | `0xd9` | 110 | 15589-15808 | 0.0008 | 1.6942 |
| `0x101` | `0xf9` | 22 | 15809-15852 | 1.7098 | 2.0379 |
| `0x101` | `0xf8` | 1 | 15853-15854 | 2.0535 | 2.0535 |

The two `0x03 = 0x00` writes at frames 15533 and 15535 are the only writes in the seven sequences without a link check after them. `0x02 = 0x30` at 15549 is replaced by `0x02 = 0x18` in the 6-pair block at 15565 before the start, so this move too runs with `0x02 = 0x18`. The capture ends with `0x02 = 0x18`, `0x09 = 0x00`, `0x33 = 0x1e` and `0x31 = 0x3b`.

## Status values

Register `0x101` has no field names in SANE's GL124 header, which defines bits only for `0x100` ([G 245-253]). SANE reads status at `0x101` for both GL124 and GL128 ([L 145-146]) and decodes it with one bit layout "same for all chips" ([L 157-176]), the layout of register `0x41` on older chips (SANE `backend/genesys/gl841_registers.h` lines 173 to 180). SANE's GL128 header repeats it for `0x101` ([R 101-111]). Plustek's engine has accessors for five of the eight bits at `0x101` with the same masks: BUFEMPTY, SCANFSH, HOMESNR, LAMPSTS, MOTORENB ([M 199-203]).

| Bit | Mask | Name | SANE meaning [L 169-176] | `0xd5` | `0xf5` | `0xf4` | `0xdc` | `0xdd` | `0xf1` | `0xf8` | `0xfd` | `0xfc` | `0xd9` | `0xf9` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7 | `0x80` | PWRBIT | clear: replugged | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| 6 | `0x40` | BUFEMPTY | buffer empty | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| 5 | `0x20` | FEEDFSH | feeding finished | 0 | 1 | 1 | 0 | 0 | 1 | 1 | 1 | 1 | 0 | 1 |
| 4 | `0x10` | SCANFSH | scanning finished | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| 3 | `0x08` | HOMESNR | at home | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 |
| 2 | `0x04` | LAMPSTS | lamp on | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 0 |
| 1 | `0x02` | FEBUSY | front end busy | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0 | `0x01` | MOTORENB | motor enabled | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 1 | 1 |

Where the values occur: `0xd5` in moves 2 to 4 and before the park, `0xf5` and `0xf4` in moves 1 to 4, `0xdc` before move 1, `0xdd` at the start of move 1, `0xf1` in the park, `0xf8` before the reverse and exit moves, `0xdd`, `0xfd`, `0xfc` in the reverse move, `0xd9`, `0xf9`, `0xf8` in the exit move. LAMPSTS follows the lamp register: set when `0x03 = 0x30` (LAMPPWR [G 57]), clear with `0x20` and `0x00`.

Move 3 in detail. The last `0x101` read before the start (frame 6433, 244.8281 s) is `0xf4`, the state move 2 left behind: feed finished, motor off. The start write is submitted at 244.8364 s (frame 6483). Then:

1. `0xd5` from the first read, 0.6 ms after the start, for 38 reads: the motor is enabled and FEEDFSH is clear. No counter clear (`0x0d`) is written before the start. The last `0x0d` write is at frame 6019. pyopticfilm notes that on the 8200i SE the previous feed's completion may still show after a start without a counter clear (`src/pyopticfilm/asic/gl128.py` lines 1492 to 1495). Here the stale FEEDFSH is gone at the first read.
2. `0xf5` first at 0.5853 s (frame 6563). The last `0xd5` was at 0.5697 s. FEEDFSH set, motor still enabled.
3. `0xf4` first at 1.0861 s (frame 6627). The last `0xf5` was at 1.0704 s. MOTORENB clear.

So FEEDFSH came between 0.570 s and 0.585 s after the start and MOTORENB cleared between 1.070 s and 1.086 s, about 0.5 s after FEEDFSH. The driver polls every 15.5 ms on average (5.9 ms to 16.0 ms) and reads `0x33` 15.6 ms after the first read with MOTORENB clear. What the motor does between FEEDFSH and MOTORENB clearing (deceleration or a hold time) is not visible. Between the first reads that show each change, that gap is 0.50 s in move 3, 0.34 s in move 2 and in both moves with BACKSCAN, and 0.13 s in move 4.

## Direction

Facts from the capture:

- Every move starts with `0x02 = 0x18`. MTRREV (`0x02` bit 2 [G 49]) is clear in all 61 writes of `0x02` in the capture (values `0x00`, `0x08`, `0x18`, `0x30`, `0x58`, `0x78`). SANE's GL124 backend reverses with MTRREV ([H 502-503]). This driver never does.
- `0x09` bit 3 (BACKSCAN [G 96, M 63]) is set for exactly two moves: the move between the passes (written at 7391, cleared at 7923) and the move at the end (15561, cleared at 15855). All other writes of `0x09` are `0x00`. SANE never sets BACKSCAN: at `a8676a6` `REG_0x09_BACKSCAN` is defined in the headers and used nowhere in the code.
- Apart from BACKSCAN, the exit move has the same table, `0x02`, LPERIOD, `0xa0`, STEPNO, FASTNO, FSHDEC and FMOVNO as move 2. Its register state differs from move 2's in `0x03`, `0x05`, `0x09`, `0x0d`, LINCNT, `0x2a`, `0x2b`, `0x31`, `0x33` (bit 1), FEEDL, STRPIXEL and ENDPIXEL.
- HOMESNR (bit 3 of `0x101`):

| Sequence | Before the start | During the move | After |
|---|---|---|---|
| Move 1 | set (`0xdc`, frames 6075, 6089) | set in the first read (`0xdd`, frame 6283), clear in every later read | clear |
| Moves 2 to 4 | clear | clear | clear |
| Image 1 (AGOHOME) | clear | clear | clear until 256.40 s, set at 268.16 s |
| Reverse (BACKSCAN) | set (`0xf8`) | set in all 244 reads | set |
| Exit (BACKSCAN) | set (`0xf8`) | set in all 133 reads | set |

Reading of these facts *(inference)*:

- Without BACKSCAN, the motor moves the carrier away from the home sensor: move 1 starts on the sensor and leaves it, and the carrier stays off the sensor through moves 2 to 4 and the image. This is the direction that draws the holder into the scanner.
- AGOHOME brings the carrier back onto the home sensor after the image, without a start write of its own.
- With BACKSCAN, the motor runs the other way, toward the slot. Both BACKSCAN moves start on the home sensor and keep it set for 2176 and 961 steps, so the sensor stays covered beyond the home position on that side. The capture has no BACKSCAN move that starts off the sensor and no move without BACKSCAN that starts on it, other than move 1 of each cycle.
- FASTFED is set in every move and does not encode the direction. BACKSCAN is the only direction bit this driver uses.

## Slope tables

All ten moves upload one 512-byte payload twice, first to `0x1000c000`, then to `0x10010000`. Both payloads of each pair are identical (SHA-256 compared for all ten pairs). There are four distinct payloads, kept in `tables/` as hex dumps:

| File | First sent | Used by | SHA-256 |
|---|---|---|---|
| `tables/slope-6267.hex` | 6267 | move 1 of both cycles | `47a4f0bc51c2a53ed0298d2b2e5e4bfdb0af3a40c5d812cacb470d2934b2d7a2` |
| `tables/slope-6353.hex` | 6353 | moves 2 and 3 of both cycles, exit move | `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` |
| `tables/slope-6653.hex` | 6653 | move 4 of both cycles | `838b1154f780d8d8550ae565bbb143170e0caa17acd8ceb35b9dceca45402c92` |
| `tables/slope-7419.hex` | 7419 | reverse move | `a73cbf604e186370e5113abc8343bbd1f7a13ca4d3a94f22b31b798a8b537a76` |

So moves 1 to 4 use three tables: move 2 and move 3 share one.

Read as 256 16-bit little endian words (entries 37, 96 and 126 are the last of the first 38, 97 and 127 entries: STEPNO and FASTNO, the FEEDL of move 3, FMOVNO of moves 1 and 2):

| Table | Entry 0 | Entry 1 | Entry 2 | Entry 37 | Entry 96 | Entry 126 | Entry 255 |
|---|---|---|---|---|---|---|---|
| `slope-6267` | 23121 | 25316 | 18867 | 5594 | 3759 | 3355 | 2500 |
| `slope-6353` | 48780 | 52631 | 38461 | 10050 | 6514 | 5747 | 4166 |
| `slope-6653` | 48780 | 14492 | 9876 | 1948 | 1147 | 986 | 666 |
| `slope-7419` | 47619 | 51948 | 38095 | 10025 | 6504 | 5747 | 4166 |

- Little endian gives the ramp. From entry 1 to entry 255 every table is non-increasing in little endian. Big endian rises between neighbours 18 to 44 times per table.
- Entry 0 does not follow the ramp in three of the four tables: it is lower than entry 1. In `slope-6653`, entry 0 is 48780, the same value as entry 0 of `slope-6353`, followed by 14492.
- The ramp fills all 256 entries. No table ends in a run of equal values: the last entries of `slope-6353` are `0x1060`, `0x1058`, `0x104f`, `0x1046`, still falling.
- `slope-7419` is close to `slope-6353`: the two agree at 114 of the 256 entries, including the last four, and differ by at most 1161 elsewhere (entry 0).
- The table of moves 2 and 3 ends at 4166, against 2500 for move 1 and 666 for move 4. If the entries are step periods, as in SANE and pyopticfilm, the table of moves 2 and 3 is the slowest of the four at its end *(inference)*.
- How many entries a move uses is not in the payload. SANE's GL124 backend writes the table length into STEPNO, FASTNO, FSHDEC and FMOVNO ([H 517], [H 533-535]). Here STEPNO and FASTNO are 38 (32 and 48 for the reverse move), FSHDEC 1, FMOVNO 127 (moves 1, 2, reverse, exit) or 255 (moves 3, 4) *(inference that the registers play the same role)*.

The format matches what pyopticfilm uses for the 8200i SE, with different values:

- pyopticfilm packs 16-bit entries little endian (`src/pyopticfilm/asic/motor.py` lines 126 to 132, `slope_table_to_bytes`, and `src/pyopticfilm/asic/gl128.py` lines 170 to 176, `_u16_table_bytes`), as SANE does ([N 525-528]).
- For the SE it replays 256-entry tables from captures (`src/pyopticfilm/device/tables_8200i_se.py` lines 23 to 57 and 62 to 97) and sends the same table to `0x1000c000` and `0x10010000` (`src/pyopticfilm/asic/gl128.py` lines 1223 to 1225 and 1433 to 1436), as the OF120 driver does. The SE tables fall from entry 0: the fast ramp from 5854 to 208, the slow ramp from 8116 to 1041. The OF120 tables start at 23121 to 52631 and end at 666 to 4166.
- The generated tables of `create_scan_slope_table` and `create_fast_slope_table` (`src/pyopticfilm/asic/motor.py` lines 88 to 123, through `create_slope_table_for_speed` at lines 54 to 77) are a different shape: entries 0 and 1 equal (lines 36 to 38), length set by the ramp, then padded with the final value (lines 73 to 76).

The three payloads before each image, to `0x10000000`, `0x10004000` and `0x10008000` (frames 6825, 6833, 6841, SHA-256 `dc01345e633535be5a0d1c975320721a3c502ff23e02581c3f9960f2b063f72b`, all three identical), are not motor moves and are not kept in `tables/`. They are a little endian ramp too, from 24242 down to 976 at entry 37, then 976 to the end: 38 ramp entries, the value of STEPNO and FASTNO. SANE's GL124 backend puts its SCAN, BACKTRACK and STOP slope tables at those three addresses ([N 585-589], [T 95-99]), and pyopticfilm's per-channel exposure tables for the SE are flat (`src/pyopticfilm/device/tables_8200i_se.py` lines 106 to 125). So these look like scan slope tables, not exposure tables *(inference)*. The walkthrough calls them channel tables.

## What the capture does not show

- How far the carrier travels per FEEDL step, and whether FEEDL counts the acceleration steps. SANE's GL124 backend subtracts the acceleration distance from FEEDL ([H 538-553]). Whether the GL128 does is open.
- Whether moves 1 and 2 would stop on their own at 10158 and 980 steps. Both get FEEDL 1 right after the interrupt.
- What the interrupt bytes `0x40`, `0x20` and `0x04` report.
- What bit 5 of `0x33` (GPIO22 in Plustek's CGL126 class [M 247]) does. The driver sets it for moves 2, 3 and both BACKSCAN moves and clears it for moves 1 and 4, always as a read-modify-write: it reads `0x33`, writes `0x02` and `0x0a`, then writes back the read value with only bit 5 changed (eight times in the sequences above, frames 6329 to 6339, 6435 to 6445, 6449 to 6459, 6629 to 6639, 7377 to 7387, 7927 to 7937, 15547 to 15557, 15859 to 15869, and four times in the second cycle). No other write in the capture changes bit 5. The moves with bit 5 set use the tables that end at 4166 *(inference: a motor driver setting that goes with the slower tables)*.
- Whether MTRPWR, left set after every polled move, keeps the motor energised.
- Any move with BACKSCAN that starts with the carrier off the home sensor.

## Reproducing

```
sha256sum work/downloads/gitlab-sane-project/issue-151-optifilm120-usb-capture/Optifilm120
python3 -I tools/usbpcap/decode.py work/downloads/gitlab-sane-project/issue-151-optifilm120-usb-capture/Optifilm120 --full-data > work/captures/151/transfers-full.jsonl
```

`transfers-full.jsonl` is about 17 MB for the 6.6 MB capture. The listings, status runs and register state were generated from it with a throwaway script (not in the repository) that pairs requests with `annotate_gl128.pair_transactions`, classifies them like `annotate_gl128.py` and replays register writes in submit order. The listings can be checked against `work/captures/151/annotated.txt` (commands in `of120-capture-151.md`), which shows the same requests with the link checks folded into the request before them. The hex dumps are reproduced as described in `tables/README.md`.
