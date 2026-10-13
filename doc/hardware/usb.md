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

## Standby

The owner found the power button LED orange and the logo LED off (standby, per `../manual/quick-guide.md`) at 20:38. One press woke it: orange off, blue logo LED on, and the device enumerated at once. It then left the bus again at 20:43:20, 4 min 54 s after enumerating, again with no host software talking to it. Two runs agree within a second: with no host traffic, the scanner leaves the bus about 5 minutes after waking. LED state at the moment of the drop is still to be observed (expected: orange on, blue off). Whether host traffic resets the timer is not known yet.

## Power

The scanner runs from its own 24 V / 0.7 A adapter (owner, 2026-10-13), so it should not draw its operating power from USB. The `lsusb -v` capture will confirm this through the self-powered bit in the configuration descriptor.

## Host caveat

The Pi 3 reports undervoltage continuously (`vcgencmd get_throttled` = `0x50005`: under-voltage now and since boot, throttled now and since boot; 147 "Undervoltage detected" kernel messages in the first 54 minutes of uptime). The scanner has its own supply, so the remaining risk is on the Pi side: the SoC, the onboard USB hub (`0424:9514`) and the Wi-Fi dongle all run from the Pi's 5 V input, and the supply has to be ruled out before a USB failure seen on this host is blamed on the scanner.
