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
- A working OpticFilm 120 enumerates as `07b3:1406` (Plustek) with the same bcdDevice `0x0702` (Genesys GL128). This unit reports Genesys defaults instead, so the Windows driver (which matches only `07b3:1406`) cannot bind to it. Evidence in `../research.md`.
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
- The link check returns `aa`, never seen in the capture, where it was only read after the driver's first writes. Whether `aa` means "not initialised" or points at the fault is open. `CIOUSB::check_toggle_r` and `CIOUSB::Do_toggle_R` in the macOS driver do not explain it: `check_toggle_r` (`0x0f88e0`) tracks the parity of bulk IN packets, and `Do_toggle_R` (`0x0f8970`) evens it out with a dummy 4-byte bulk read at `0x01000000`.

## Standby

The owner found the power button LED orange and the logo LED off (standby, per `../manual/quick-guide.md`) at 20:38. One press woke it: orange off, blue logo LED on, and the device enumerated at once. It then left the bus again at 20:43:20, 4 min 54 s after enumerating, again with no host software talking to it. Two runs agree within a second: with no host traffic, the scanner leaves the bus about 5 minutes after waking. LED state at the moment of the drop is still to be observed (expected: orange on, blue off). Read-only host traffic does not reset it: on the third run (woken 19:46:28 UTC) the probe polled the link check and register `0x101` every 20 s, and the unit still left the bus at 19:51:23, 4 min 55 s after waking, with the last successful read at 19:51:09. Whether a full driver initialisation changes the timer is open; the OpticFilm 120 configuration in Plustek's macOS driver has `StandbyReg` and `StandbyOffTime 15` (`../vendor-driver/macos.md`).

## Power

The scanner runs from its own 24 V / 0.7 A adapter (owner, 2026-10-13), so it should not draw its operating power from USB. The `lsusb -v` capture will confirm this through the self-powered bit in the configuration descriptor.

## Host caveat

The Pi 3 reports undervoltage continuously (`vcgencmd get_throttled` = `0x50005`: under-voltage now and since boot, throttled now and since boot; 147 "Undervoltage detected" kernel messages in the first 54 minutes of uptime). The scanner has its own supply, so the remaining risk is on the Pi side: the SoC, the onboard USB hub (`0424:9514`) and the Wi-Fi dongle all run from the Pi's 5 V input, and the supply has to be ruled out before a USB failure seen on this host is blamed on the scanner.
