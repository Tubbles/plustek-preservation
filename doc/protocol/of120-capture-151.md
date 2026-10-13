# OpticFilm 120 USB capture (SANE issue #151)

Annotated walkthrough of the only public USB capture of a working OpticFilm 120: the file `Optifilm120` attached to [SANE issue #151](https://gitlab.com/sane-project/backends/-/issues/151), taken on Windows with Plustek's driver during a VueScan preview of a film strip ("two exposures as I recall", per the issue). Local copy: `work/downloads/gitlab-sane-project/issue-151-optifilm120-usb-capture/Optifilm120` (untracked).

Decoded with `tools/usbpcap/decode.py` (one JSON object per USBPcap record) and `tools/usbpcap/annotate_gl128.py` (GL124/GL128 operation listing). Outputs: `work/captures/151/transfers.jsonl` and `work/captures/151/annotated.txt` (untracked). Commands are at the end.

Conventions:

- Frame numbers are record numbers in the capture file, as Wireshark numbers them. A request and its completion are two frames. A range such as 73-76 includes the link check that follows the request.
- Times are seconds since frame 1.
- Request framing follows SANE `backend/genesys/scanner_interface_usb.cpp` (register read lines 50 to 57, register write 97 to 106, `write_0x8c` 180 to 184, buffer header 383 to 407) with the codes in `low.h` lines 105 to 119. Requests are written as `bmRequestType bRequest wValue`, for example `c0 04 018e`.
- "Link check" is the one-byte read `c0 0c 008e` with wIndex `0x20`, which returns `0x55` after nearly every write (name from pyopticfilm's 8200i SE notes, `8200i-se/02_cold_boot_open/NOTES.md` line 60).
- *(inference)* marks an interpretation, not an observation.
- Register name sources, cited as [tag line]: [G] SANE `backend/genesys/gl124_registers.h`, [H] SANE `backend/genesys/gl124.cpp`, [S] SANE `backend/genesys/gl128.cpp`, [L] SANE `backend/genesys/low.cpp`, [P] pyopticfilm `docs/register-reference.md`. SANE is the checkout in `work/downloads/sane-project/sane-backends-git`, pyopticfilm the one in `work/downloads/github-jboneng/pyopticfilm-git`, the sibling captures are in `work/downloads/github-jboneng/pyopticfilm_captures-subset`. GL124 field names are applied to the GL128 by analogy *(inference)*. pyopticfilm reports that the GL124 bit layout of register `0x01` matches what it confirmed on GL128 captures ([P 29]).

## Overview

| Item | Value |
|---|---|
| Format | classic pcap, little endian, microsecond timestamps, link type 249 (USBPcap) |
| Records | 15878 frames, 7939 request and completion pairs, none unpaired |
| Start | 2019-10-13 21:48:15 UTC (frame 1) |
| Duration | 320.28 s |
| Devices | one: bus 3, address 1 |
| Device descriptor | `07b3:1406`, bcdDevice `0x0702`, class `ff/ff/ff`, iManufacturer 10, iProduct 11, iSerialNumber 0 (frames 2, 8, 12) |
| Product string | index 11, `"Film Scanner  "` (frame 10). The manufacturer string is never requested. |
| Configuration | 39 bytes, identical to the owner's unit (`../hardware/usb.md`): self powered, 10 mA, bulk `0x81` and `0x02` of 512 bytes, interrupt `0x83` of 1 byte with bInterval 8 (frame 4) |

Control requests (submit count):

| Request | Code | Count | Notes |
|---|---|---|---|
| Register write | `40 04 0083` | 899 | 1 to 32 address and value pairs per transfer |
| Register write, address 0x100 and up | `40 04 0183` | 12 | always `0x114 = 0x80`, `0x115 = 0x80` |
| Register read | `c0 04 008e` | 98 | `0x06` ×2, `0x31` ×54, `0x33` ×31, `0x36` ×11 |
| Register read, address 0x100 and up | `c0 04 018e` | 3610 | `0x101` ×3392, `0x100` ×98, `0x102` to `0x105` ×30 each |
| One-byte read, wIndex `0x20` | `c0 0c 008e` | 1008 | always `0x55` (link check) |
| One-byte read, wIndex `0x18` | `c0 0c 008e` | 66 | always `0x02`, after every buffer transfer |
| One-byte read, wIndex `0x00` | `c0 0c 008e` | 3 | always `0x00` (frames 125, 159, 7373) |
| `write_0x8c` | `40 0c 008c` | 18 | wIndex `0x10` and `0x13`, value `0x0d` every time |
| Buffer header, read | `40 04 0082`, wIndex 0 | 40 | all at address `0x10000000` |
| Buffer header, write | `40 04 0082`, wIndex 1 | 36 | |
| `0x8a` and `0x8b` requests | `c0 0c 008a`, `40 0c 008b`, `40 04 008b`, `c0 04 008a` | 6 | frames 15 to 72 only, see "Non-volatile storage" |
| `0x8d` write | `40 0c 008d` | 2 | after each image (frames 7143, 15307) |
| Standard | GET_DESCRIPTOR | 4 | plus 3 injected by USBPcap (frames 1 to 6) |

Bulk and interrupt:

| Endpoint | Transfers | Bytes | Content |
|---|---|---|---|
| `0x81` IN | 2080 | 10,396,992 | calibration: 16 × 3072, 4 × 81732, 8 × 574464. Images: 2 × (5 × 522792 + 98640) = 2 × 2,712,600 |
| `0x02` OUT | 46 | 105,472 | 10 shading tables to `0x10014000` (9112 declared bytes, sent as 9216), 20 slope tables of 512 bytes to `0x1000c000` and `0x10010000`, 6 channel tables of 512 bytes to `0x10000000`, `0x10004000`, `0x10008000` |
| `0x83` IN | 8 | 6 | see "Interrupt endpoint" |

Every buffer read header uses wIndex `0x00`. The streaming mode wIndex `0x08` that the 8200i SE driver used for its preview (`8200i-se/03_home_or_preview/NOTES.md` lines 166 to 175) does not occur.

Register `0x101` (status) values over 3392 reads: `0xe9` 558, `0xd5` 557, `0xc9` 518, `0xed` 401, `0xcd` 386, `0xdd` 223, `0xf5` 163, `0xc5` 115, `0xd9` 110, `0xe5` 103, `0xf1` 66, `0xdc` 49, `0xd8` 46, ten others fewer than 25 times. Bit 7 is set in every read, as on the 8200i SE (`03_home_or_preview/NOTES.md` line 56).

## Does the capture start at device open?

Partly.

- Frames 1 to 6 carry IRP id 0 and one shared timestamp, and hold GET_DESCRIPTOR device, GET_DESCRIPTOR configuration and SET_CONFIGURATION with their answers. This is the descriptor set USBPcap writes at capture start for devices already present, not bus traffic *(inference from the IRP id and timestamp. pyopticfilm's session 03 notes record the same "inject descriptors" option, `03_home_or_preview/NOTES.md` line 7)*. The scanner was therefore enumerated and configured before the capture began.
- The first vendor request is frame 15 at 18.08 s, and the driver's whole open sequence follows (frames 15 to 138). The capture holds everything the driver sent to open the device.
- Whether the scanner had been initialised by an earlier session (warm start) cannot be decided from the capture. SANE tests cold or warm with bit 4 (`PWRBIT`) of register `0x06` ([L 1477-1483]), and this driver reads `0x06` only at 256.40 s and 301.35 s (frames 7287, 15451, value `0x18`), long after writing `0x06 = 0x18` itself. The one-byte read at wIndex `0x00` (frame 125, `0x00`) is the USB speed byte in SANE ([L 1463-1474], bit 3 set means USB 1.x), not a cold or warm flag. pyopticfilm's notes call it an "ASIC initialised?" probe (`02_cold_boot_open/NOTES.md` lines 33 and 59). The first status read after the blast (`0x101 = 0xdc`, frames 73 to 76) equals what the 8200i SE returned after its blast following a power cycle (SE capture `02_cold_boot_open.pcapng` frames 785 to 788).

## Phases

| Frames | Time (s) | What happens |
|---|---|---|
| 1-6 | 0.000 | USBPcap's injected descriptors (see above). |
| 7-10 | 15.486 to 15.491 | Device descriptor and product string (index 11). No vendor request. *(inference: the host application or WIA enumerating the device)* |
| 11-16 | 18.076 to 18.079 | Driver open: device descriptor, string descriptor 0 (language `0x0409`), then the first vendor request (`0x8a`, wIndex `0x26fe`). |
| 17-138 | 18.105 to 18.222 | Boot: register blast, clock set-up, serial flash ID and 64-byte read, AFE defaults, GPIO set-up. Detailed below. |
| none | 18.222 to 231.701 | No traffic for 213.5 s. *(inference: VueScan idle until the preview was started)* |
| 139-268 | 231.701 to 231.898 | Re-initialisation: GPIO and status reads, the blast twice (open values with the lamp bit set, then a scan register set), AFE defaults, lamp on (`0x03 = 0x30`). |
| 269-3076 | 231.898 to 235.617 | Calibration, round 1: memory layout, AFE offset and gain search on one-line strips (3072 bytes each) plus one 81732-byte read, lamp off (`0x03 = 0x20`), a 128-line pass (574464 bytes), shading table upload, lamp on, a 128-line pass with `0x01 = 0x23` (DVDSET), second shading upload. The order matches SANE's GL128 shading for the 8200i SE: "AFE probes, dark strip, unity table, lamp on, white strip, measured table" ([S 1044-1045], dark strip with the lamp off and white strip with DVDSET per [S 976]). *(inference for the dark and white roles on the OF120)* |
| 3077-5976 | 235.628 to 238.726 | Calibration, round 2: another blast and the same sequence, with AFE register 0 = `0x0070` instead of `0x00f8` and different `0x33` values. Purpose not determined. |
| 5977-6844 | 238.731 to 247.130 | Set-up and positioning: blast, AFE offsets and gains from round 1, shading upload, memory layout shifted by 4 words, then four motor moves with `0x02 = 0x18` (MTRPWR and FASTFED [G 47-48]) and FEEDL 10158, 980, 97 and 5592 steps, each preceded by a slope table pair to `0x1000c000` and `0x10010000`. The interrupt endpoint is used on the first two moves. |
| 6845-7142 | 247.142 to 255.305 | Image 1: channel tables to `0x10000000`, `0x10004000`, `0x10008000`, lamp on, `0x02 = 0x30` (AGOHOME and MTRPWR), LINCNT 825, `0x01 = 0x23`, start, then six buffer reads, 2,712,600 bytes (825 × 3288). |
| 7143-7314 | 255.363 to 256.401 | End of pass: `0x8d` write, lamp `0x20`, `0x01 = 0x22`, status polling, read `0x06`, `0x02 = 0x30`. *(inference: park, as the 8200i SE does with AGOHOME, [S 593-597])* |
| 7315-7352 | 257.005 to 268.152 | Idle, register `0x31` read 19 times. |
| 7353-7928 | 268.158 to 271.997 | A move with `0x09 = 0x08` (bit 3, BACKSCAN in [G 96]) and FEEDL 2176, status polled until done, then `0x09 = 0x00`. |
| 7929-13444 | 271.998 to 278.645 | Calibration rounds 1 and 2 again, same structure as above. |
| 13445-15024 | 278.646 to 292.108 | Set-up and positioning: FEEDL 10158, 980, 97 and 37449. |
| 15025-15306 | 292.110 to 300.263 | Image 2: 2,712,600 bytes. |
| 15307-15478 | 300.312 to 301.350 | End of pass as in frames 7143 to 7314. |
| 15479-15532 | 301.907 to 318.004 | Idle, register `0x31` read 27 times. |
| 15533-15878 | 318.004 to 320.279 | Lamp `0x03 = 0x00`, `0x31` bit 7 cleared, `0x02 = 0x30`, a move with `0x09 = 0x08` and FEEDL 961, `0x09 = 0x00`, `0x02 = 0x18`, `0x31 = 0x3b`. The capture ends. *(inference: the holder is moved out)* |

Two positioning facts tie the moves to the film holder *(inference)*: the last positioning move differs between the two images (5592 and 37449 steps, consistent with two frames of one strip), and the second move of each cycle is 980 steps, the value of `FilmLoaderOrigin = 0,980` in the OpticFilm 120 configuration of Plustek's macOS driver (`ScanInfoVID_07B3_PID_1406.plist` lines 96 to 97, see "Non-volatile storage").

## Boot sequence

This section lists every register and AHB write before the first bulk read (frame 539, a 3072-byte calibration strip at 232.05 s). There is no AHB (buffer) write in that span: the first one is frame 2145 at 233.62 s, a shading table.

### Open (frames 15 to 138, 18.08 s to 18.22 s)

| Step | Frames | Request | Result or note |
|---|---|---|---|
| 1 | 15-16 | `c0 0c 008a`, wIndex `0x26fe`, 1 byte | `0x00`. Meaning unknown. |
| 2 | 17-32 | four register writes of 32, 32, 32 and 20 pairs | the blast, next table |
| 3 | 33-36 | `40 04 0183`: `0x114 = 0x80`, `0x115 = 0x80` | |
| 4 | 37-44 | `write_0x8c` index `0x10` = `0x0d`, index `0x13` = `0x0d` | SANE's GL124 boot writes `0x0b` and `0x0e` here ([H 1278-1279]), the 8200i SE `0x0c` and `0x0c` ([S 1578-1579]) |
| 5 | 45-56 | `0x0b = 0x64`, `0x13 = 0x0f`, `0x0b = 0x6c` | |
| 6 | 57-72 | serial flash ID read and 64-byte read | see "Non-volatile storage" |
| 7 | 73-76 | read `0x101` twice | `0xdc`, `0xdc` |
| 8 | 77-80 | `0x03 = 0x00` | lamp register |
| 9 | 81-112 | eight AFE writes, each one transfer `0x51 = index, 0x5d = high, 0x5e = low` | AFE 0 = `0x00f8`, 1 = `0x0080`, 2 to 7 = `0x0000` |
| 10 | 113-118 | read `0x36` → `0xfc`, write `0x36 = 0xfe` | sets bit 1. GL124 uses `0x36` as GPIO output enable ([H 1252-1253]). |
| 11 | 119-124 | read `0x33` → `0x0e`, write `0x33 = 0x0e` | |
| 12 | 125-126 | `c0 0c 008e`, wIndex `0x00`, 1 byte | `0x00` (USB 2.0 per [L 1463-1474]) |
| 13 | 127-138 | read `0x31` → `0xbe`, write `0x31 = 0x3e`, read → `0x3e`, write `0x31 = 0xbe` | bit 7 of `0x31` held low for 13 ms. The blast wrote `0x31 = 0xfc` but `0xbe` reads back, so some bits of `0x31` are inputs *(inference)*. |

### The register blast (frames 17 to 36)

Columns: frame of the transfer, register, value the OF120 driver wrote, value in pyopticfilm's 8200i SE boot table `INIT_REGS` (`src/pyopticfilm/device/gl128_common.py` lines 31 to 52, equal to the blast in the SE capture `8200i-se/02_cold_boot_open/02_cold_boot_open.pcapng` frames 749 to 764, checked with these tools), and the name where a source gives one. The 116 addresses come in the same order and the same four transfer boundaries as on the SE (`0x01`-`0x23`, `0x24`-`0x5b`, `0x5c`-`0x86`, `0x87`-`0xbf`). 28 values differ. `0x114` and `0x115` follow in their own transfer.

| Frame | Register | OF120 | 8200i SE | Name or meaning |
|---|---|---|---|---|
| 17 | `0x01` | `0x22` | `0x22` | scan control: DVDSET 0x20, SHDAREA 0x02, SCAN 0x01 [G 33-41] |
| 17 | `0x02` | `0x78` | `0x78` | motor: AGOHOME 0x20, MTRPWR 0x10, FASTFED 0x08, MTRREV 0x04 [G 43-51] |
| 17 | `0x03` | `0x20` | `0x20` | lamp: XPASEL 0x20, LAMPPWR 0x10 [G 53-58] |
| 17 | `0x04` | `0x02` | `0x02` | LINEART, BITSET 0x40, FILTER, AFEMOD 0x07 [G 60-64] |
| 17 | `0x05` | `0xc8` | `0x48` **differs** | DPIHW 0xc0, MTLLAMP 0x30, GMMENB 0x08, ENB20M, MTLBASE [G 66-75] |
| 17 | `0x06` | `0x18` | `0x18` | SCANMOD 0xe0, PWRBIT 0x10, GAIN4 0x08 [G 77-82] |
| 17 | `0x07` | `0x00` | `0x00` | LAMPSIM 0x80 [G 84] |
| 17 | `0x08` | `0x80` | `0x00` **differs** | DRAM2X 0x80, MPENB, CIS_LINE, IR2_ENB, IR1_ENB, ENB24M [G 86-91] |
| 17 | `0x09` | `0x00` | `0x00` | MCNTSET, EVEN1ST, BLINE1ST, BACKSCAN 0x08, OUTINV, SHORTTG [G 93-98] |
| 17 | `0x0a` | `0x48` | `0x40` **differs** | SIFSEL 0xc0, SHEETFED 0x20, LPWMEN 0x10 [G 103-107] |
| 17 | `0x0b` | `0x6c` | `0x6c` | CLKSET 0xe0, RFHDIS 0x10, ENBDRAM 0x08, DRAMSEL 0x07 [G 109-124] |
| 17 | `0x0c` | `0x00` | `0x00` |  |
| 17 | `0x0d` | `0x00` | `0x00` | clear counters: CLRMCNT 0x04, CLRDOCJM 0x02, CLRLNCNT 0x01 [G 126-131] |
| 17 | `0x11` | `0x00` | `0x00` |  |
| 17 | `0x12` | `0x04` | `0x04` |  |
| 17 | `0x13` | `0x08` | `0x08` |  |
| 17 | `0x14` | `0x01` | `0x01` |  |
| 17 | `0x15` | `0x80` | `0x80` |  |
| 17 | `0x16` | `0x01` | `0x27` **differs** | TOSHIBA 0x40 and clock inversion bits [G 135-142] |
| 17 | `0x17` | `0x0c` | `0x0c` | TGMODE 0xc0, SNRSYN 0x0f [G 144-145] |
| 17 | `0x18` | `0x14` | `0x10` **differs** | CNSET, DCKSEL, CKTOGGLE, CKDELAY, CKSEL [G 147-152] |
| 17 | `0x19` | `0x00` | `0x02` **differs** |  |
| 17 | `0x1a` | `0x00` | `0x00` | SW2SET, SW1SET, CK4INV, CK3INV, MANUAL [G 154-160] |
| 17 | `0x1b` | `0x00` | `0x00` |  |
| 17 | `0x1c` | `0x00` | `0x00` | TBTIME 0x07 [G 162] |
| 17 | `0x1d` | `0x00` | `0x00` | CK4LOW, CK3LOW, CK1LOW, LINESEL 0x1f [G 164-169] |
| 17 | `0x1e` | `0x10` | `0x10` | WDTIME 0xf0 [G 171-173] |
| 17 | `0x1f` | `0x00` | `0x00` |  |
| 17 | `0x20` | `0x0c` | `0x0c` |  |
| 17 | `0x21` | `0x00` | `0x00` |  |
| 17 | `0x22` | `0x1a` | `0x1a` |  |
| 17 | `0x23` | `0x00` | `0x00` |  |
| 21 | `0x24` | `0x1a` | `0x1a` |  |
| 21 | `0x25` | `0x00` | `0x00` | LINCNT, 24 bit [G 258] |
| 21 | `0x26` | `0x00` | `0x00` | LINCNT |
| 21 | `0x27` | `0x00` | `0x00` | LINCNT |
| 21 | `0x2b` | `0x20` | `0x20` | shading dummy clock [P 24] |
| 21 | `0x2c` | `0x12` | `0x12` | DPISET, 16 bit [G 260] |
| 21 | `0x2d` | `0xc0` | `0xc0` | DPISET |
| 21 | `0x30` | `0x6f` | `0x6f` | GPIO area [H 44-60] |
| 21 | `0x31` | `0xfc` | `0x00` **differs** | GPIO area, written by the GL124 GPIO layout [H 44-60] |
| 21 | `0x32` | `0x6b` | `0x22` **differs** | GPIO9 to GPIO16 [G 177-185] |
| 21 | `0x33` | `0x0e` | `0x04` **differs** | GPIO17 in bit 0 on GL124 [H 1255-1258], REG_DEPTH_A in pyopticfilm [P 27] |
| 21 | `0x34` | `0x80` | `0x80` | GPIO area [H 44-60] |
| 21 | `0x35` | `0x7f` | `0x2f` **differs** | GPIO area [H 44-60] |
| 21 | `0x36` | `0xfc` | `0x1c` **differs** | GPIO output enable, GPOE17 in bit 0 on GL124 [H 1252-1253] |
| 21 | `0x37` | `0x30` | `0xc0` **differs** | REG_IR, bit 2 infrared LED on the 8200i SE [P 32] |
| 21 | `0x38` | `0x77` | `0x44` **differs** | GPIO area [H 44-60] |
| 21 | `0x39` | `0x02` | `0x00` **differs** |  |
| 21 | `0x3a` | `0x00` | `0x00` |  |
| 21 | `0x3b` | `0xff` | `0xff` |  |
| 21 | `0x3c` | `0xff` | `0xff` |  |
| 21 | `0x3d` | `0x00` | `0x00` | FEEDL, 24 bit [G 261] |
| 21 | `0x3e` | `0x00` | `0x00` | FEEDL |
| 21 | `0x3f` | `0x01` | `0x01` | FEEDL |
| 21 | `0x4f` | `0x03` | `0x03` |  |
| 21 | `0x52` | `0x07` | `0x07` |  |
| 21 | `0x53` | `0x09` | `0x09` |  |
| 21 | `0x54` | `0x0b` | `0x0b` |  |
| 21 | `0x55` | `0x01` | `0x01` |  |
| 21 | `0x56` | `0x03` | `0x03` |  |
| 21 | `0x57` | `0x05` | `0x05` |  |
| 21 | `0x5a` | `0x12` | `0x12` |  |
| 21 | `0x5b` | `0x00` | `0x00` |  |
| 25 | `0x5c` | `0x00` | `0x40` **differs** |  |
| 25 | `0x5e` | `0x1f` | `0x1f` | AFE data low when used after 0x51 [P 35] |
| 25 | `0x5f` | `0x01` | `0x05` **differs** |  |
| 25 | `0x60` | `0x00` | `0x00` | LED4TG, YENB, YBIT, ACYNCNRLC, ENOFFSET, LEDADD, CK4ADC, AUTOCONF [G 194-202] |
| 25 | `0x61` | `0x00` | `0x00` |  |
| 25 | `0x63` | `0x20` | `0x20` |  |
| 25 | `0x67` | `0x7f` | `0x7f` |  |
| 25 | `0x68` | `0x7f` | `0x7f` |  |
| 25 | `0x69` | `0x01` | `0x01` |  |
| 25 | `0x70` | `0x06` | `0x01` **differs** |  |
| 25 | `0x71` | `0x09` | `0x02` **differs** |  |
| 25 | `0x72` | `0x08` | `0x03` **differs** |  |
| 25 | `0x73` | `0x09` | `0x04` **differs** |  |
| 25 | `0x74` | `0x00` | `0x00` | CK1MAP, 24 bit [G 262] |
| 25 | `0x75` | `0x00` | `0x00` | CK1MAP |
| 25 | `0x76` | `0x00` | `0x00` | CK1MAP |
| 25 | `0x77` | `0x00` | `0x00` | CK3MAP, 24 bit [G 263] |
| 25 | `0x78` | `0x00` | `0x00` | CK3MAP |
| 25 | `0x79` | `0x00` | `0x0f` **differs** | CK3MAP |
| 25 | `0x7a` | `0x00` | `0xff` **differs** | CK4MAP, 24 bit [G 264] |
| 25 | `0x7b` | `0x00` | `0xff` **differs** | CK4MAP |
| 25 | `0x7c` | `0x00` | `0xff` **differs** | CK4MAP |
| 25 | `0x7d` | `0x00` | `0x00` | LPERIOD on GL124 [G 265], EXPOSURE in pyopticfilm [P 36] |
| 25 | `0x7e` | `0x75` | `0x2a` **differs** | see 0x7d |
| 25 | `0x7f` | `0x30` | `0xf8` **differs** | see 0x7d |
| 25 | `0x80` | `0x00` | `0x00` | DUMMY [G 266] |
| 25 | `0x81` | `0x22` | `0x22` |  |
| 25 | `0x82` | `0x00` | `0x00` | STRPIXEL, 24 bit [G 267, P 37] |
| 25 | `0x83` | `0x01` | `0x01` | STRPIXEL |
| 25 | `0x84` | `0x18` | `0x18` | STRPIXEL |
| 25 | `0x85` | `0x00` | `0x00` | ENDPIXEL, 24 bit [G 268, P 38] |
| 25 | `0x86` | `0x00` | `0x00` | ENDPIXEL |
| 29 | `0x87` | `0x00` | `0x00` | ENDPIXEL |
| 29 | `0x93` | `0x00` | `0x00` | SEGCNT, 24 bit [G 273] |
| 29 | `0x94` | `0x00` | `0x00` | SEGCNT |
| 29 | `0x95` | `0x00` | `0x00` | SEGCNT |
| 29 | `0x9d` | `0x08` | `0x08` |  |
| 29 | `0xa0` | `0x12` | `0x12` | FSTPSEL 0x38, STEPSEL 0x07 [G 207-211] |
| 29 | `0xa4` | `0x00` | `0x00` | STEPNO [G 276] |
| 29 | `0xa5` | `0x20` | `0x20` | STEPNO, pixel clock in SANE GL128 [S 57] |
| 29 | `0xa6` | `0x00` | `0x00` | FWDSTEP [G 277] |
| 29 | `0xa7` | `0x80` | `0x00` **differs** | FWDSTEP |
| 29 | `0xa8` | `0x00` | `0x00` | BWDSTEP [G 278] |
| 29 | `0xa9` | `0x80` | `0x00` **differs** | BWDSTEP |
| 29 | `0xaa` | `0x00` | `0x00` | FASTNO [G 279] |
| 29 | `0xab` | `0x30` | `0x30` | FASTNO, pixel clock in SANE GL128 [S 57] |
| 29 | `0xb8` | `0x00` | `0x00` |  |
| 29 | `0xb9` | `0x38` | `0x38` |  |
| 29 | `0xba` | `0x00` | `0x00` |  |
| 29 | `0xbd` | `0x00` | `0x00` |  |
| 29 | `0xbe` | `0x00` | `0x00` |  |
| 29 | `0xbf` | `0x00` | `0x00` |  |
| 33 | `0x114` | `0x80` | not at boot | named only [G 255] |
| 33 | `0x115` | `0x80` | not at boot | named only [G 256] |

### Re-initialisation before the preview (frames 139 to 538, 231.70 s to 232.05 s)

| Frames | Requests |
|---|---|
| 139-160 | read `0x101` → `0xdc`, `0x31` → `0xbb`, `0x101` → `0xdc`, `0x36` → `0xfe`, write `0x36 = 0xfe`, read `0x33` → `0x0e`, write `0x33 = 0x0c`, read `0x101` → `0xdc`, wIndex `0x00` read → `0x00` |
| 161-180 | the blast again: the same 118 values as frames 17 to 36 except `0x03 = 0x30`, with `0x33` and `0x36` moved to the end of the last transfer |
| 181-190 | read `0x101` → `0xdc`, `write_0x8c` `0x10` = `0x0d`, `0x13` = `0x0d` |
| 191-214 | a blast with scan values, 131 pairs. Different from frames 17 to 36: `0x03=0x30 0x16=0xb7 0x18=0x40 0x1d=0x20 0x20=0x05 0x22=0x06 0x24=0x0f 0x33=0x1e 0x37=0x32 0x52=0x08 0x53=0x0a 0x54=0x00 0x55=0x02 0x56=0x04 0x57=0x06 0x5a=0x11 0x5b=0x49 0x5f=0x00 0x61=0x98 0x70=0x02 0x71=0x03 0x72=0x04 0x73=0x05 0x76=0x3f 0x79=0x3f 0x7c=0x3f 0x7e=0x80 0x7f=0x00 0xa0=0x0a`. Added: `0x58=0x07 0x59=0x07 0x88=0x00 0x89=0x00 0x8a=0x00 0x8b=0x55 0x8c=0x00 0x8d=0x00 0x8e=0x55 0x8f=0x00 0x90=0x01 0x91=0x54 0x92=0x00`, then `0x114 = 0x115 = 0x80` |
| 215-246 | AFE defaults as at open |
| 247-264 | read `0x101` → `0xdc`, `0x03 = 0x30` (lamp on), read `0x36` → `0xfc`, write `0xfe`, read `0x33` → `0x1e`, write `0x1c` |
| 265-332 | read `0x101` → `0xdc` twice, then the memory layout, one or two registers per transfer: `0xd0 = 0xd1 = 0xd2 = 0x0a`, `0xe0` to `0xf8` = `00 c4 15 f7 15 f8 2b 2b 2b 2c 40 5f 40 60 55 93 55 94 6a c7 6a c8 7f fb 05` |
| 333-336 | strip set-up, 32 pairs: `0x2c=0x12 0x2d=0xc0 0x80=0x00 0x81=0x11 0x82=0x00 0x83=0x00 0x84=0x11 0x85=0x00 0x86=0x02 0x87=0x11 0x04=0x42 0x01=0x02 0x05=0xc0 0x02=0x00 0xa2=0x00 0xa3=0x00 0x3d=0x00 0x3e=0x00 0x3f=0x01 0xa6=0x00 0xa7=0x01 0xa8=0x00 0xa9=0x01 0x1d=0x20 0xa4=0x00 0xa5=0x01 0xac=0x00 0xad=0x01 0x0d=0x04 0x25=0x00 0x26=0x00 0x27=0x01` |
| 337-340 | `0x28=0x00 0x29=0x55 0x2a=0x4f 0x2b=0x01` |
| 341-364 | AFE 2 to 4 = `0x0000`, AFE 5 to 7 = `0x0080` |
| 365-384 | `0x0d = 0x05` twice, `0x0d = 0x07`, `0x01 = 0x03`, `0x0f = 0x01` (start) |
| 385-538 | read `0x101`: `0xcd` ×31, `0xed` ×39, `0xbd`, read `0x102` to `0x105` → `00 00 00 ea`, buffer read header, address `0x10000000`, 3072 bytes |

## Differences from the 8200i SE boot

Compared with pyopticfilm's `Gl128.asic_boot()` and `init()` (`src/pyopticfilm/asic/gl128.py` lines 1246 to 1277) and its tables in `src/pyopticfilm/device/gl128_common.py`, and with the SE cold-boot capture they were taken from (`8200i-se/02_cold_boot_open/02_cold_boot_open.pcapng`, device address 16, frames 735 to 870, annotated with these tools). SANE's `CommandSetGl128::asic_boot` ([S 1386-1623]) follows that capture's order.

| Step | OF120 (this capture) | 8200i SE capture | pyopticfilm |
|---|---|---|---|
| String descriptor read by the driver | index 0, language IDs (13-14) | index 12, the serial number (745-746) | none |
| First vendor request | `c0 0c 008a` wIndex `0x26fe` → `0x00` (15) | `c0 0c 008e` wIndex `0x00` → `0x00` (747) | none |
| AHB boot blobs at `0x000fff00` and `0x000fff01`, 34 bytes each | absent | after the AFE writes (829-844) | first step (`gl128.py` lines 1253 to 1254) |
| Register blast | 116 addresses, 28 values differ (17-32) | `INIT_REGS` (749-764) | `INIT_REGS` (line 1255) |
| `0x114 = 0x115 = 0x80` | at boot (33-36) | not at boot | only in `SCAN_REGS` (`gl128_common.py` line 99) |
| `write_0x8c` `0x10`, `0x13` | `0x0d`, `0x0d` (37-44) | `0x0c`, `0x0c` (765-772) | not sent |
| `0x0b`, `0x13`, `0x0b` | `0x64`, `0x0f`, `0x6c` (45-56) | `0x44`, `0x0f`, `0x4c` (773-784) | not sent. The blast has `0x0b = 0x6c`, `SCAN_REGS` `0x0b = 0x4c` (`gl128_common.py` line 90) |
| Serial flash ID and 64-byte read | yes (57-72) | absent | absent |
| Read `0x101` twice | `0xdc` (73-76) | `0xdc` (785-788) | |
| Lamp register `0x03` | `0x00` (77-80) | `0x10`, then `0x00` (789-796) | |
| AFE 0 to 7 | `0x00f8 0x0080` then zeros (81-112) | same (797-828) | same, `FRONTEND_REGS` (`gl128_common.py` lines 68 to 77) |
| GPIO read-modify-writes | `0x36` bit 1 set, `0x33` rewritten as `0x0e`, `0x31` bit 7 low for 13 ms (113-138) | `0x33` written `0x07`, `0x07`, `0x17`, `0x1f` (845-868) | none |
| USB speed byte (wIndex `0x00`) | after the blast (125) | before the blast (747) | |
| Memory layout `0xd0` to `0xf8` | not at boot, but before the first strip (269-332), other values | not in this session | at boot (line 1256) |
| GPO registers `0xa2` to `0xae` | blast has `0xa7 = 0xa9 = 0x80`, and `0xa2 0xa3 0xac 0xad` are first written at frame 333 | blast only, `0xa7 = 0xa9 = 0x00` | `GPO_REGS` at boot (line 1258) |
| Table uploads during init | none until the shading table at 2145 | none in this session | `upload_tables()` (line 1270) |

Blast values that differ, with GL124 field readings where [G] names the bits:

- `0x05`: `0xc8` against `0x48`. Bits 7 and 6 are DPIHW in [G 66-71]: 4800 against 1200 class.
- `0x08`: `0x80` against `0x00`. Bit 7 is DRAM2X [G 86].
- `0x0a`: `0x48` against `0x40`. Bit 3 has no GL124 name.
- `0x16` and `0x18` (sensor clock fields in [G 135-152]) and `0x19`.
- `0x31`, `0x32`, `0x33`, `0x35`, `0x36`, `0x37`, `0x38` (the GPIO area of [H 44-60], and pyopticfilm's `0x33` and `0x37`) and `0x39`. Board wiring differs between the models *(inference)*.
- `0x5c`, `0x5f`, `0x70` to `0x73`, `0x79` to `0x7c` (CK3MAP and CK4MAP in [G 263-264]).
- `0x7d` to `0x7f`: `0x007530` (30000) against `0x002af8` (11000). LPERIOD in [G 265], EXPOSURE in [P 36].
- `0xa7`, `0xa9`: `0x80` against `0x00`.

Register `0x0b` is `0x6c` in both blasts, but the start-up writes after `write_0x8c` leave it at `0x6c` on the OF120 and `0x4c` on the SE. CLKSET (bits 7 to 5) reads 48 MHz against 40 MHz in [G 119-124], while ENBDRAM and DRAMSEL `0x04` are the same. With `write_0x8c` `0x0d` against `0x0c`, this suggests a different clock set-up on the OF120 *(inference)*.

Memory layout, read as 16-bit big-endian pairs like the SE notes do (`03_home_or_preview/NOTES.md` lines 128 to 147):

| | `0xe0` to `0xf7` | `0xf8` |
|---|---|---|
| OF120, before calibration (frames 269-332) | `00c4 15f7 15f8 2b2b 2b2c 405f 4060 5593 5594 6ac7 6ac8 7ffb` | `05` |
| OF120, before positioning (frames 6091-6154 and 6193-6256) | `00c8 15fb 15fc 2b2f 2b30 4063 4064 5597 5598 6acb 6acc 7fff` | `05` |
| 8200i SE (`gl128_common.py` lines 56 to 63) | `0068 0b00 0b01 1599 159a 2032 2033 2acb 2acc 3564 3565 3ffd` | `05` |

Both use six segments. The OF120 segments are `0x1534` words each, the SE's `0xa99`, so the OF120 layout spans about twice the memory.

## Interrupt endpoint 0x83

The endpoint is used: 8 transfers, all around the first two positioning moves of each cycle.

| Submit frame | Time | Completion frame | Time | USBD status | Data | Context |
|---|---|---|---|---|---|---|
| 6257 | 238.945 | 6258 | 238.947 | 0 | `04` | before move 1 is set up |
| 6285 | 238.952 | 6286 | 242.855 | 0 | `40` | after the start of move 1 (frame 6279, FEEDL 10158) |
| 6343 | 243.070 | 6344 | 243.176 | `0xc0010000` | none | cancelled |
| 6371 | 243.196 | 6372 | 244.456 | 0 | `20` | after the start of move 2 (frame 6365, FEEDL 980) |
| 13725 | 278.848 | 13726 | 278.852 | 0 | `40` | before move 1 is set up |
| 13753 | 278.857 | 13754 | 282.768 | 0 | `40` | after the start of move 1 (frame 13747) |
| 13809 | 282.976 | 13810 | 283.082 | `0xc0010000` | none | cancelled |
| 13837 | 283.102 | 13838 | 284.120 | 0 | `20` | after the start of move 2 (frame 13831) |

- Each answered read is one byte with a single bit set: `0x04`, `0x40` or `0x20`.
- The driver submits the read right after `0x0f = 0x01` (start) of moves 1 and 2, and the completion arrives when the move has finished: the next request is `0x02 = 0x08`, which clears MTRPWR ([G 47]) (frames 6287, 6373, 13755, 13839). Moves 3 and 4 are followed by polling `0x101` only.
- `0xc0010000` is `USBD_STATUS_CANCELED` (mingw-w64 `mingw-w64-headers/include/usb.h`). The driver cancels the pending read about 0.1 s after submitting it.
- The first read of each cycle completes within 4 ms (`0x04` in cycle 1, `0x40` in cycle 2), so the endpoint seems to hold an event from before the read was submitted *(inference)*.
- The 8200i SE and 8100 V2 captures show no traffic on `0x83` (SE sessions 02 and 03, 8100 V2 session 02, checked with `decode.py`), and pyopticfilm does not use it (`8200i-se/01_enumerate/NOTES.md` lines 75 to 76). During moves the SE driver polls the one-byte read at wIndex `0x21` instead (`03_home_or_preview/NOTES.md` lines 81 to 84, [S 753-758]). The OF120 driver never sends wIndex `0x21`.
- Plustek's macOS engine has `InitInterrupt`, `ReadInterrupt`, `GetInterruptVal` and `ReadButtonID` (symbol names in `PLK_A120.framework/Versions/A/ScanApi`, see `../vendor-driver/macos.md`), so the endpoint may also carry button events *(inference from the names)*.

## Safe probe set

Read requests from the start of the session, in capture order, with the values the working OF120 returned. Byte strings are hex in wire order.

Only frames 7 to 16 come before the driver's first write (frame 17). Every other value below was read after the driver had written registers, so on a unit that has not been through the same writes it may legitimately differ. Whether a read has side effects on GL128 (for example a status bit that clears when read) is not known. pyopticfilm describes bit 7 of `0x101` as "clear = replugged/cold since last check" ([P 41]).

### A. Before any write

| # | Frames | bmRequestType | bRequest | wValue | wIndex | wLength | Returned |
|---|---|---|---|---|---|---|---|
| A1 | 7-8 | `0x80` | `0x06` | `0x0100` | `0x0000` | 18 | `12 01 00 02 ff ff ff 40 b3 07 06 14 02 07 0a 0b 00 01` |
| A2 | 9-10 | `0x80` | `0x06` | `0x030b` | `0x0409` | 257 | 30 bytes: `1e 03` then UTF-16LE `"Film Scanner  "` |
| A3 | 11-12 | `0x80` | `0x06` | `0x0100` | `0x0000` | 18 | same as A1 |
| A4 | 13-14 | `0x80` | `0x06` | `0x0300` | `0x0000` | 255 | `04 03 09 04` |
| A5 | 15-16 | `0xc0` | `0x0c` | `0x008a` | `0x26fe` | 1 | `00` |

The owner's unit reports its product string at index 2, not 11 (`../hardware/usb.md`), so A2 there is wValue `0x0302`.

### B. Read-only vendor requests after the first writes

| # | Frames | bmRequestType | bRequest | wValue | wIndex | wLength | Returned | Register and context |
|---|---|---|---|---|---|---|---|---|
| B1 | 19-20, then after nearly every write | `0xc0` | `0x0c` | `0x008e` | `0x0020` | 1 | `55` | link check, 1008 times, always `0x55` |
| B2 | 73-74 | `0xc0` | `0x04` | `0x018e` | `0x0122` | 2 | `dc 55` | `0x101`, after the blast and steps 3 to 6 of the open |
| B3 | 75-76 | `0xc0` | `0x04` | `0x018e` | `0x0122` | 2 | `dc 55` | `0x101` again |
| B4 | 113-114 | `0xc0` | `0x04` | `0x008e` | `0x3622` | 2 | `fc 55` | `0x36`, the blast wrote `0xfc` |
| B5 | 119-120 | `0xc0` | `0x04` | `0x008e` | `0x3322` | 2 | `0e 55` | `0x33`, the blast wrote `0x0e` |
| B6 | 125-126 | `0xc0` | `0x0c` | `0x008e` | `0x0000` | 1 | `00` | USB speed byte ([L 1463-1474]) |
| B7 | 127-128 | `0xc0` | `0x04` | `0x008e` | `0x3122` | 2 | `be 55` | `0x31`, the blast wrote `0xfc` |
| B8 | 133-134 | `0xc0` | `0x04` | `0x008e` | `0x3122` | 2 | `3e 55` | `0x31`, after writing `0x3e` |
| B9 | 139-140 | `0xc0` | `0x04` | `0x018e` | `0x0122` | 2 | `dc 55` | `0x101`, 213 s after the open, no traffic in between |
| B10 | 141-142 | `0xc0` | `0x04` | `0x008e` | `0x3122` | 2 | `bb 55` | `0x31` |
| B11 | 143-144 | `0xc0` | `0x04` | `0x018e` | `0x0122` | 2 | `dc 55` | `0x101` |
| B12 | 145-146 | `0xc0` | `0x04` | `0x008e` | `0x3622` | 2 | `fe 55` | `0x36` |
| B13 | 151-152 | `0xc0` | `0x04` | `0x008e` | `0x3322` | 2 | `0e 55` | `0x33` (after a write of `0x36 = 0xfe`) |
| B14 | 157-158 | `0xc0` | `0x04` | `0x018e` | `0x0122` | 2 | `dc 55` | `0x101` (after a write of `0x33 = 0x0c`) |
| B15 | 159-160 | `0xc0` | `0x0c` | `0x008e` | `0x0000` | 1 | `00` | USB speed byte |

Later reads, for reference: `0x100` (wValue `0x018e`, wIndex `0x0022`) returned `0xb0`, `0x31`, `0x33` or `0x37`. `0x06` (wIndex `0x0622`) returned `0x18`. `0x102` to `0x105` returned the word count SANE reads there ([L 239-243]). The one-byte read at wIndex `0x18` returned `0x02` after every buffer transfer.

### C. The serial flash read (contains OUT requests)

Frames 57 to 72, right after the blast and the clock set-up (steps 2 to 5 of the open). Three of the five requests are writes with request code `0x8b`, whose effect is not documented anywhere this project has read. They are listed for completeness, and replaying them is a decision for the owner.

| # | Frames | bmRequestType | bRequest | wValue | wIndex | wLength | Data out | Returned |
|---|---|---|---|---|---|---|---|---|
| C1 | 57-58 | `0x40` | `0x0c` | `0x008b` | `0x0007` | 1 | `01` | |
| C2 | 61-62 | `0x40` | `0x04` | `0x008b` | `0x0009` | 4 | `00 00 00 00` | |
| C3 | 65-66 | `0xc0` | `0x04` | `0x008a` | `0x0010` | 3 | | `c2 20 13` |
| C4 | 67-68 | `0x40` | `0x04` | `0x008b` | `0x000b` | 4 | `00 00 00 00` | |
| C5 | 71-72 | `0xc0` | `0x04` | `0x008a` | `0x000f` | 64 | | 64 bytes, below |

C1, C2 and C4 are each followed by a link check returning `0x55` (frames 59-60, 63-64, 69-70). There are 12 ms without traffic between the link check after the last start-up write (frame 56) and C1.

The 64 bytes returned by C5:

```
b4 14 00 00 1d 02 00 00 ff 28 00 00 44 02 00 00
4a 02 00 00 dd 28 00 00 58 02 00 00 ff ff ff ff
ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
```

As 32-bit little-endian words: 5300, 541, 10495, 580, 586, 10461, 600, then `0xff` fill.

## Non-volatile storage and the USB identity

### The serial flash read at open (frames 57 to 72)

- C3 returns `c2 20 13`. flashrom's `include/flashchips.h` defines `MACRONIX_ID 0xC2` and `MACRONIX_MX25L4005 0x2013` ("Same as MX25L4005A, MX25L4005C, MX25L4006E"), a 4 Mbit (512 KiB) SPI NOR flash. Read as a JEDEC ID, the issue #151 unit has a Macronix MX25L4005-class serial flash behind the ASIC *(inference: that the 3-byte answer is a JEDEC read-ID reply)*.
- C5 returns 64 bytes, seven 32-bit values and `0xff` fill. `0xff` is the erased state of NOR flash.
- The OpticFilm 120 configuration in Plustek's macOS driver (`work/extracted/mac-V3100-payload/Library/Application Support/LaserSoft Imaging/SupportFiles/Plustek/PLK_A120.framework/Versions/A/Resources/ScanInfoVID_07B3_PID_1406.plist`) contains `flash_addr_Postive_IR_Scaling = 0,0x00000,0x00040` (lines 65 to 66): an item at flash address 0 of size `0x40`, 64 bytes, the size C5 returns. The same file has `Enable_IR_Scaling = 5300,1322,11328,751,1381,11314,757` (lines 94 to 95), seven numbers starting with 5300 in the same pattern of small and large values as the flash words (5300, 541, 10495, 580, 586, 10461, 600), and `FlashRAM = 1` (lines 102 to 103). So C5 reads the unit's infrared scaling record at flash address 0, with the plist values as defaults *(inference)*. One of the values, 580, is also the STRPIXEL the driver programs for the shading and positioning passes (registers `0x82` to `0x84`, frames 1435, 2239, 4393, 5167, 6259). That match may be a coincidence.
- The macOS `ScanApi` binary contains `SFlash_RDID`, `SFlash_Read`, `SFlash_Write`, `SFlash_WREN`, `SFlash_SectorErase`, `SFlash_BlockErase`, `SFlash_ChipErase`, `SPI_init`, `SPI_WriteTxData`, `SPI_ReadRxData`, `SPI_ReadBusData` and `SPI_WriteBusData` (grep of the binary, also listed in `../vendor-driver/macos.md`). The five requests fit "set up SPI, read the ID, read 64 bytes at address 0" *(inference)*. Which wIndex selects which operation is for the disassembly planned in `../work/0007-identity-and-flash.md`. One detail for that work: `0x0b` is also the common SPI fast-read opcode, and a 4-byte payload would fit a 3-byte address plus a dummy byte. This may be a coincidence.
- Only the open at 18.1 s reads the flash. The re-initialisations at 231.7 s and later do not.

### Where the identity appears in the capture

- The VID and PID bytes `b3 07 06 14` occur in the capture file only in the three device descriptor answers (frames 2, 8 and 12, file offsets 128, 473 and 713), and the UTF-16 product string only in frame 10 (offset 581). A search of the whole file, full bulk payloads included, finds neither `Plustek` nor `Genesys` in ASCII or UTF-16.
- No request reads or writes anything that looks like descriptor data. The 64-byte flash block holds seven numbers and `0xff` fill.
- No request writes to the flash *(inference)*: there is no erase or program sequence among the `0x8a` and `0x8b` requests, and the only `0x8b` writes are C1, C2 and C4. This assumes that flash access goes only through `0x8a` and `0x8b`. The two `0x8d` writes (frames 7143 and 15307) are of unknown effect too.
- iSerialNumber is 0 on this unit, as on the owner's. The 8200i SE has a serial string at index 12 (SE capture frames 735-736 and 745-746).
- The 8200i SE boot writes two 34-byte blobs to AHB addresses `0x000fff00` and `0x000fff01`, which pyopticfilm lists as unexplained ([P 50]). The OF120 driver does not write them.

### What this suggests for the owner's unit

Hypothesis, not verified: the OpticFilm 120 board carries a serial flash that the vendor driver reads through the ASIC. If the GL128 also loads its USB descriptors from that flash at power-on, a blank, damaged or unreadable flash would explain why the owner's unit reports Genesys defaults with string indices 1 and 2. Nothing in this capture shows where the descriptors come from, so this remains open.

A direct test on the owner's unit is to replay set C and compare the ID and the 64-byte block. An answer of `c2 20 13` with a block shaped like the one above would show that the flash is present and readable through the ASIC. `00 00 00` or `ff ff ff` would point at the flash, its wiring or the ASIC's SPI interface. Set C contains three writes of unknown effect, see above.

### Other unexplained requests

- Frame 15, `c0 0c 008a` with wIndex `0x26fe`, returns `0x00`. SANE names wValue `0x8a` `GPIO_READ` (`low.h` line 115) and uses it only on the GL646, with wIndex 0 (`gl646.cpp` line 381). What `0x26fe` selects is not known.
- Frames 7143 and 15307, `40 0c 008d` with wIndex 0 and data `00`, come right after the last image buffer read of each pass. `0x8d` has no name in SANE's `low.h`.
- Requests C2 to C5 use request code `0x04` with the value codes SANE calls `GPIO_READ` and `GPIO_WRITE` (`low.h` lines 115 to 116). Neither SANE nor pyopticfilm sends them.

## Open questions

1. Which SPI operation each `0x8a` and `0x8b` wIndex selects (`0x07`, `0x09`, `0x0b`, `0x0f`, `0x10`), and whether other flash addresses can be read the same way. Only address 0, 64 bytes, is shown.
2. Where the USB descriptors live (serial flash, ASIC defaults, or both), and when the ASIC reads them.
3. What the first request (`0x8a`, wIndex `0x26fe`) and the `0x8d` write after each image do.
4. What the interrupt values `0x04`, `0x40` and `0x20` mean, and why only the first two moves of each cycle use the endpoint.
5. Why calibration runs twice per cycle, with AFE register 0 = `0x00f8` in one round and `0x0070` in the other.
6. Which bits of `0x31` are inputs. Bit 6 read 1 at 258.85 s and 308.72 s and 0 otherwise. What the 13 ms low pulse on bit 7 at open does.
7. Whether CLKSET in `0x0b` and the `0x8c` value `0x0d` select a 48 MHz clock on the GL128 (GL124 field names only).
8. Whether reads of `0x100` and `0x101` change latched state.
9. Whether the open in this capture was a cold or a warm start.
10. What the final move with `0x09` bit 3 set does.

## Reproducing

```
python3 -I tools/usbpcap/decode.py work/downloads/gitlab-sane-project/issue-151-optifilm120-usb-capture/Optifilm120 > work/captures/151/transfers.jsonl
python3 -I tools/usbpcap/annotate_gl128.py work/captures/151/transfers.jsonl > work/captures/151/annotated.txt
python3 -I -m unittest discover -s tools/usbpcap
```

`decode.py --device <address>` keeps one device, which the sibling captures need (address 16 in `8200i-se/02_cold_boot_open`).
