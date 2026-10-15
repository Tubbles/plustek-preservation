# USB identity and behaviour

Observations of the owner's unit. Each entry says where it came from.

## Enumeration (Raspberry Pi 3, 2026-10-13)

From `dmesg` on the test Raspberry Pi 3 (Linux 6.18.50+rpt-rpi-v8, `dwc_otg` host controller):

```
19:43:13 usb 1-1.4: new high-speed USB device number 6 using dwc_otg
19:43:13 usb 1-1.4: New USB device found, idVendor=05e3, idProduct=0103, bcdDevice= 7.02
19:43:13 usb 1-1.4: New USB device strings: Mfr=1, Product=2, SerialNumber=0
19:43:13 usb 1-1.4: Product: USB2.0 Scanner
19:43:13 usb 1-1.4: Manufacturer: Genesys
19:48:08 usb 1-1.4: USB disconnect, device number 6
```

- Vendor `05e3` is Genesys Logic, not Plustek (`07b3`). Product `0103` is not in the `usb.ids` database. Neighbouring Genesys IDs in `usb.ids` are other film scanners: `0120` Pacific Image PrimeFilm 1800u, `0142` "Multiple Slides Scanner-3600", `0143` "Multiple Frames Film Scanner-36series", `0145` Reflecta CrystalScan 7200, `0180` "Plustek Scanner".
- A working OpticFilm 120 enumerates as `07b3:1406` (Plustek) with the same bcdDevice `0x0702` (Genesys GL126 on the board, GL128 in SANE's naming, `../research.md`). This unit reports Genesys defaults instead, so the Windows driver (which matches only `07b3:1406`) cannot bind to it. Evidence in `../research.md`.
- No kernel driver bound to it (expected: scanners are driven from user space).
- The device disconnected 4 min 55 s after enumerating, with no host software talking to it. See the standby section below.

## Descriptors (2026-10-13 20:38, after a wake from standby)

Full dump in `lsusb-v.txt`, captured by `tools/pi/watch-scanner.sh`. Summary:

| Field | Value |
|---|---|
| Device class / subclass / protocol | 255 / 255 / 255 (vendor specific) |
| bcdUSB | 2.00, high speed |
| bMaxPacketSize0 | 64 |
| Strings | manufacturer "Genesys", product "USB2.0 Scanner", no serial string |
| Configurations | 1, self powered (`bmAttributes 0xc0`, device status `0x0001`), MaxPower 10 mA |
| Interface 0 | 3 endpoints, class 255/255/255 |
| EP `0x81` | bulk IN, 512 bytes |
| EP `0x02` | bulk OUT, 512 bytes |
| EP `0x83` | interrupt IN, 1 byte, bInterval 8 (2^(8-1) microframes = 16 ms at high speed) |

The bulk pair is the data path (commands and image data). A one-byte interrupt endpoint is a typical carrier for button and sensor state (power, eject, holder inserted). Both readings are interpretations of the descriptor layout, to be confirmed against the vendor driver and captures.

## Read-only probe (2026-10-13 19:46 UTC)

`tools/pi/probe_readonly.py`, run by the watcher right after a wake from standby. Raw output: `probes/20261013T194628Z-readonly.jsonl`. Every request is an IN request that Plustek's driver also sends (`../protocol/of120-capture-151.md`); nothing was written.

| Request | This unit | Working unit (capture, values read after the driver's writes unless noted) |
|---|---|---|
| Strings | language `0409`; 1 = "Genesys", 2 = "USB2.0 Scanner"; index 11 does not exist | index 11 = "Film Scanner  " |
| `c0 0c 008a 26fe` (first request at open) | `00` | `00` (before any write) |
| `c0 0c 008e 0020` ("link check") | `aa` | always `55` |
| `c0 0c 008e 0000` (USB speed byte) | `00` (high speed) | `00` |
| register `0x101` (status) | `4c` | `dc` |
| register `0x06` | `00` | `18` |
| register `0x31` | `bc` | `be`, `3e`, `bb` |
| register `0x33` | `1e` | `0e` |
| register `0x36` | `00` | `fc`, `fe` |
| interrupt `0x83`, 200 ms | nothing | (used only during moves) |

Every register read came back in the GL124/GL128 framing (value then `55`), so the ASIC's USB register interface works while the unit reports the Genesys default identity. A driver can talk to the unit as it is.

Readings, all to be confirmed:
- Register `0x06` bit 4 (PWRBIT, SANE `low.cpp` 1477 to 1483) is clear and register `0x101` bit 7 is clear, both of which mean a cold ASIC that no driver has initialised since power-up. Expected, since nothing has initialised it.
- The link check returns `aa`, never seen in the capture, where it was only read after the driver's first writes. Right after an OUT request it returns `55` like the working unit (`flash-dump.md`), and at any other time `aa` again, also after the open (`probes/20261015T061444Z-vendor-open.jsonl`, the `watch` records). The Windows engine uses this byte as its write acknowledge and resends a write unless bit 0 is set (`../protocol/playbook.md`, "Status and flags"), so `aa` with no write pending is not a fault sign *(inference)*. `CIOUSB::check_toggle_r` and `CIOUSB::Do_toggle_R` in the macOS driver do not explain it: `check_toggle_r` (`0x0f88e0`) tracks the parity of bulk IN packets, and `Do_toggle_R` (`0x0f8970`) evens it out with a dummy 4-byte bulk read at `0x01000000`.

## Standby

The owner found the power button LED orange and the logo LED off (standby, per `../manual/quick-guide.md`) at 20:38. One press woke it: orange off, blue logo LED on, and the device enumerated at once. It then left the bus again at 20:43:20, 4 min 54 s after enumerating, again with no host software talking to it. Two runs agree within a second: with no host traffic, the scanner leaves the bus about 5 minutes after waking. LED state at the moment of the drop is still to be observed (expected: orange on, blue off). Read-only host traffic does not reset it: on the third run (woken 19:46:28 UTC) the probe polled the link check and register `0x101` every 20 s, and the unit still left the bus at 19:51:23, 4 min 55 s after waking, with the last successful read at 19:51:09. Whether a full driver initialisation changes the timer is open; the OpticFilm 120 configuration in Plustek's macOS driver has `StandbyReg` and `StandbyOffTime 15` (`../vendor-driver/macos.md`).

Driving the vendor's standby line does not hold it either. On the wake of 2026-10-14 22:16:55 UTC the watcher ran `tools/pi/keep_awake.py` one second after enumeration: `0x31` read `bc` before and after (GPIO8 already high as an input), `0x34` went from `00` to `80`, so GPIO8 was driven high as an output from then on (`probes/20261014T221655Z-keep-awake.jsonl`). The unit still left the bus at 22:21:50, 4 min 55 s after waking, the same interval as without the write. So whatever runs the five-minute timer does not watch GPIO8 by itself; the vendor engine's `StandbyModeControl` works in a fully initialised scanner, and what else that initialisation changes is unknown. The 8051 microcontroller on the board is the natural place for such a timer (`board.md`) *(inference)*. Keep-awake is disabled again on the Pi.

The vendor's open sequence does hold it. On the wake of 2026-10-15 06:14:33 UTC, `tools/pi/vendor_open.py` replayed the open sequence of the issue #151 capture (frames 15 to 138, `../protocol/of120-capture-151.md`) 11 s after enumeration and then read the link check and `0x101` every 20 s for 7 minutes (`probes/20261015T061444Z-vendor-open.jsonl`). All 26 writes were acknowledged with `55`, and of the 10 reads only the flash ID, the infrared record and `0x31` differed from the capture, all three as already known from the earlier probes. After the sequence `0x101` read `dc` on this unit, the value the working unit returned at the same point (frames 73 and 75), and it stayed `dc` throughout the watch. The unit was still on the bus at 06:21:53 UTC, 7 min 20 s after the wake, past the 4 min 55 s of every earlier run. Which part of the sequence holds it is not known: it writes the register blast, enables GPIO outputs (`0x36 = 0xfe`, `0x33 = 0x0e`), pulses GPIO8 low (`0x31 = 0x3e`, then `0xbe` 17 ms later) and leaves `0x02 = 0x78` (ACDCDIS, AGOHOME, MTRPWR, FASTFED), so the motor holds its position from then on, as it does in the capture between the open and the first move (`../protocol/of120-moves.md`). The carrier read at home before the open (`0x101 = 0x4c`), so AGOHOME had nothing to do, and no motor sound is expected from that write. The unit was still answering register reads at 07:36 UTC, 82 minutes after the wake and 75 minutes after the last poll of the watch, through two motor runs in between (`probes/20261015T073623Z-move-carrier.jsonl`), so the open does not merely restart the five-minute countdown and the polling is not needed. The engine's own standby code, read for the playbook (`../protocol/playbook.md`, "Standby"), knows one line, GPIO8, and what the open adds to the earlier keep-awake write is a 10 ms low pulse on it. The smallest write set to try on a later wake is that pulse on top of the keep-awake writes, with a bisection order if it does not hold.

## Register snapshot (2026-10-15 08:52 UTC)

`tools/pi/snapshot.py` read the playbook's list (`../protocol/playbook.md`, "Status and flags", part 3) 2 h 38 min after the wake of 06:14:33 UTC, after the open sequence and the two move runs: 316 IN requests in 0.64 s, every register read answered with `55` as its second byte (`probes/20261015T085229Z-snapshot.jsonl`, the full map of `0x00` to `0x120`). The unit was still on the bus, so the hold of the open sequence lasts hours.

- One-byte reads: write acknowledge `aa` (no write pending), nothing on the interrupt endpoint in 200 ms, `0x8a`/`0x26fe` `00`, speed byte `00`, busy byte `02`.
- `0x101 = f8`: PWRBIT, BUFEMPTY, FEEDFSH, SCANFSH and HOMESNR set, LAMPSTS clear since the lamp run ended with `0x03 = 0x00` (the working unit read `fc` at the end of its move 3, lamp on, `../protocol/of120-moves.md`). `0x100 = b0`: DOCSNR, COVERSNR, CHKVER, the value the working unit returned in its calibration rounds (`../protocol/playbook.md`, "Status and flags"). Both read the same in steps 6 and 9.
- Read-back of the written state: of the 171 registers the working unit's driver had written by the end of move 3 (capture frame 6644, every `40 04 0083`/`0183` pair replayed), 165 read back with the written value. The six others: `0x02 = 08` and `0x03 = 00` are the move tool's own last writes; `0x0f = 00` after the start command `01`, so the command register clears itself *(inference)*; `0x31 = bc` for a written `fc`, where bit 6 (GPIO7) is an input with `0x34 = 0x80` and the working unit read it as 0 as well (`bb`); `0x32 = e3` for a written `6b`; `0x37 = f2` in step 6 and `b2` in step 7, 15 ms apart, for a written `32`.
- The last two are the finding of this snapshot. In `0x32`, bit 3 (GPIO12) is an output by `0x35 = 0x7f` (`../protocol/gl128-registers.md`), written 1 and read 0, and bit 7 (GPIO16, input) reads 1. In `0x37`, bit 6 (GPIO31) is an output by `0x38 = 0x77`, written 0, read 1 and then 0 with no write in between, and bit 7 (GPIO32, input) reads 1. The capture never reads `0x32`, `0x37` or their output enables, so the working unit gives no value to compare. Either a set output-enable bit does not make the pin an output for these two, or something in the unit drives these registers besides the host, with the firmware's microcontroller as the candidate (`board.md`) *(inference)*. The configuration's own patches on these registers are `37.20` at the top level (plist line 23), `37.30` in `SPEED1` (line 623) and `32.10`, `37.02`, `37.30` in `SPEED2` (lines 672 to 678), none on bit 3 of `0x32` or bit 6 of `0x37`.
- Never written by the capture's driver and not zero: `0x00 = 95`, `0x99 = 1f`, `0x9b = 3f`, `0x9c = 3f`, `0xa1 = b0`, `0xbc = ff`, `0xdb = 82`, `0xde = ff`, `0xdf = ff`, `0xfd = 10`, `0x109 = 09`, `0x10a = 7c`, `0x10e = 04`, `0x120 = 18`, besides the two status registers. Power-on values or set by the firmware *(inference)*; a snapshot on a fresh wake before the open will say which of them the open changes.

A second pair of snapshots brackets a warm re-run of the open sequence (09:46:55 and 09:48:23 UTC, `probes/20261015T094655Z-snapshot.jsonl` and `probes/20261015T094823Z-snapshot.jsonl`; the open ran at 09:47:07 from the restarted watcher, exit 0). The snapshot before equals the one of 08:52 in every value, `0x37` included: again `f2` in step 6 and `b2` in step 7, an hour later, so the first read after a pause gives `f2` and the next `b2` *(inference from two pairs at the same cadence)*. The open changed 44 registers (`snapshot.py --diff`): the registers the move tool had set to move 3's values went back to the open's (`0x04`, `0x13`, `0x16`, `0x18`, `0x1d`, `0x20` to `0x24`, `0x2c`, `0x2d`, `0x3f`, `0x51` to `0x5f`, `0x61`, `0x70` to `0x7f`, `0x81` to `0x87`, `0xa0`, `0xa5`, `0xab`), `0x02` went `08` to `78` (motor powered and holding, as the open leaves it), `0x33` `1c` to `0e`, `0x101` `f8` to `d8` (FEEDFSH cleared by the reset; LAMPSTS clear since the open ends with the lamp off, where the working unit's `dc` was read during the open with the lamp still on), and `0x37` `b2` to `30`, the value written, with bits 6 and 7 clear. So with the open's `0x30` in `0x37` the register reads back as written, and with the move tool's `0x32` (GPIO26 driven high, as during the vendor's move 3) bits 6 and 7 read set and bit 6 wandered. `0x32` stayed `e3` through the open's write of `6b`, so its bit 3 is clear and its bit 7 set whatever the host writes. None of the registers the capture never writes changed.

## Power

The scanner runs from its own 24 V / 0.7 A adapter (owner, 2026-10-13), so it should not draw its operating power from USB. The motor runs briefly at power-on (owner, 2026-10-15), so the firmware moves the holder carrier on its own, before any host talks to it. Before the opening the unit reported the carrier at home after power-on (`0x101 = 0x4c`, bit 3 `HOMESNR` set, "Read-only probe"), which fits a homing move at power-on *(inference)*. After the reassembly the first reads on the wake of 2026-10-15 06:14 UTC gave the same values, `0x101 = 0x4c` and `0x31 = 0xbc` (`probes/20261015T061444Z-vendor-open.jsonl`, `registers_before_open`). So the home sensor bit was set again, and the move 1 replay of 11:40 UTC settled why: the bit cleared 0.135 s into the move and the carrier was heard moving, so the carrier sat on the sensor and the sensor works (`../work/0011-first-motor-move.md`, `probes/20261015T114043Z-move-carrier-move-1.jsonl`). The `lsusb -v` capture will confirm this through the self-powered bit in the configuration descriptor.

## Host caveat

The Pi 3 reports undervoltage continuously (`vcgencmd get_throttled` = `0x50005`: under-voltage now and since boot, throttled now and since boot; 147 "Undervoltage detected" kernel messages in the first 54 minutes of uptime). The scanner has its own supply, so the remaining risk is on the Pi side: the SoC, the onboard USB hub (`0424:9514`) and the Wi-Fi dongle all run from the Pi's 5 V input, and the supply has to be ruled out before a USB failure seen on this host is blamed on the scanner.
