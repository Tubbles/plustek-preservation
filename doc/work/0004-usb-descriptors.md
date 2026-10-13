# 0004 Capture USB descriptors

Status: done (descriptors in `doc/hardware/lsusb-v.txt`, summary in `doc/hardware/usb.md`)

`tools/pi/watch-scanner.sh` runs on the Pi and dumps `lsusb -v` on the next connect. Copy the result into `doc/hardware/usb.md` (interfaces, endpoints, max packet sizes, string descriptors).
