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
- The link check returns `aa`, never seen in the capture, where it was only read after the driver's first writes. After the first OUT request it returns `55` like the working unit (`flash-dump.md`), so `aa` is the answer before any write and not a fault sign *(inference)*. `CIOUSB::check_toggle_r` and `CIOUSB::Do_toggle_R` in the macOS driver do not explain it: `check_toggle_r` (`0x0f88e0`) tracks the parity of bulk IN packets, and `Do_toggle_R` (`0x0f8970`) evens it out with a dummy 4-byte bulk read at `0x01000000`.

## Standby

The owner found the power button LED orange and the logo LED off (standby, per `../manual/quick-guide.md`) at 20:38. One press woke it: orange off, blue logo LED on, and the device enumerated at once. It then left the bus again at 20:43:20, 4 min 54 s after enumerating, again with no host software talking to it. Two runs agree within a second: with no host traffic, the scanner leaves the bus about 5 minutes after waking. LED state at the moment of the drop is still to be observed (expected: orange on, blue off). Read-only host traffic does not reset it: on the third run (woken 19:46:28 UTC) the probe polled the link check and register `0x101` every 20 s, and the unit still left the bus at 19:51:23, 4 min 55 s after waking, with the last successful read at 19:51:09. Whether a full driver initialisation changes the timer is open; the OpticFilm 120 configuration in Plustek's macOS driver has `StandbyReg` and `StandbyOffTime 15` (`../vendor-driver/macos.md`).

Driving the vendor's standby line does not hold it either. On the wake of 2026-10-14 22:16:55 UTC the watcher ran `tools/pi/keep_awake.py` one second after enumeration: `0x31` read `bc` before and after (GPIO8 already high as an input), `0x34` went from `00` to `80`, so GPIO8 was driven high as an output from then on (`probes/20261014T221655Z-keep-awake.jsonl`). The unit still left the bus at 22:21:50, 4 min 55 s after waking, the same interval as without the write. So whatever runs the five-minute timer does not watch GPIO8 by itself; the vendor engine's `StandbyModeControl` works in a fully initialised scanner, and what else that initialisation changes is unknown. The 8051 microcontroller on the board is the natural place for such a timer (`board.md`) *(inference)*. Keep-awake is disabled again on the Pi.

The vendor's open sequence does hold it. On the wake of 2026-10-15 06:14:33 UTC, `tools/pi/vendor_open.py` replayed the open sequence of the issue #151 capture (frames 15 to 138, `../protocol/of120-capture-151.md`) 11 s after enumeration and then read the link check and `0x101` every 20 s for 7 minutes (`probes/20261015T061444Z-vendor-open.jsonl`). All 26 writes were acknowledged with `55`, and of the 10 reads only the flash ID, the infrared record and `0x31` differed from the capture, all three as already known from the earlier probes. After the sequence `0x101` read `dc` on this unit, the value the working unit returned at the same point (frames 73 and 75), and it stayed `dc` throughout the watch. The unit was still on the bus at 06:21:53 UTC, 7 min 20 s after the wake, past the 4 min 55 s of every earlier run. Which part of the sequence holds it is not known: it writes the register blast, enables GPIO outputs (`0x36 = 0xfe`, `0x33 = 0x0e`), pulses GPIO8 low (`0x31 = 0x3e`, then `0xbe` 17 ms later) and leaves `0x02 = 0x78` (ACDCDIS, AGOHOME, MTRPWR, FASTFED), so the motor holds its position from then on, as it does in the capture between the open and the first move (`../protocol/of120-moves.md`). The carrier read at home before the open (`0x101 = 0x4c`), so AGOHOME had nothing to do, and no motor sound is expected from that write. How long the unit stays up after the sequence, and whether it needs the polling, is open; the watcher logs the disconnect when it comes.

## Power

The scanner runs from its own 24 V / 0.7 A adapter (owner, 2026-10-13), so it should not draw its operating power from USB. The motor runs briefly at power-on (owner, 2026-10-15), so the firmware moves the holder carrier on its own, before any host talks to it. Before the opening the unit reported the carrier at home after power-on (`0x101 = 0x4c`, bit 3 `HOMESNR` set, "Read-only probe"), which fits a homing move at power-on *(inference)*. After the reassembly the first reads on the wake of 2026-10-15 06:14 UTC gave the same values, `0x101 = 0x4c` and `0x31 = 0xbc` (`probes/20261015T061444Z-vendor-open.jsonl`, `registers_before_open`). So the home sensor bit is set again, either because the carrier sits on the sensor or because the sensor reads set for another reason after the reassembly; a move away from home, during which the bit has to clear, tells the two apart (`../work/0011-first-motor-move.md`). The `lsusb -v` capture will confirm this through the self-powered bit in the configuration descriptor.

## Host caveat

The Pi 3 reports undervoltage continuously (`vcgencmd get_throttled` = `0x50005`: under-voltage now and since boot, throttled now and since boot; 147 "Undervoltage detected" kernel messages in the first 54 minutes of uptime). The scanner has its own supply, so the remaining risk is on the Pi side: the SoC, the onboard USB hub (`0424:9514`) and the Wi-Fi dongle all run from the Pi's 5 V input, and the supply has to be ruled out before a USB failure seen on this host is blamed on the scanner.
