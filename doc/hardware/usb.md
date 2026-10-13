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
- Open question: is `05e3:0103` the normal ID of a working OpticFilm 120, or a fallback the controller reports when its configuration is missing? See `doc/research.md`.
- No kernel driver bound to it (expected: scanners are driven from user space).
- The device disconnected 4 min 55 s after enumerating. No host software talked to it. Not yet known whether that was the standby timer, the power button, or something else.

Full descriptors (`lsusb -v`) are captured automatically by `tools/pi/watch-scanner.sh` the next time the scanner enumerates.

## Power

The scanner runs from its own 24 V / 0.7 A adapter (owner, 2026-10-13), so it should not draw its operating power from USB. The `lsusb -v` capture will confirm this through the self-powered bit in the configuration descriptor.

## Host caveat

The Pi 3 reports undervoltage continuously (`vcgencmd get_throttled` = `0x50005`: under-voltage now and since boot, throttled now and since boot; 147 "Undervoltage detected" kernel messages in the first 54 minutes of uptime). The scanner has its own supply, so the remaining risk is on the Pi side: the SoC, the onboard USB hub (`0424:9514`) and the Wi-Fi dongle all run from the Pi's 5 V input, and the supply has to be ruled out before a USB failure seen on this host is blamed on the scanner.
