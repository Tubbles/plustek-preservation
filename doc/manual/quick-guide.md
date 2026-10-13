# Notes from the OpticFilm 120 Quick Guide

Facts taken from the printed Plustek "OpticFilm 120 Quick Guide" that came in the box (2012, part number 17-07-3A65480-D), written up in our own words. Only what matters for supporting the hardware is kept. The scans of the booklet stay outside the repository because the scan of the DVD case shows the license serial.

## In the box

The scanner, power adapter, USB cable, the guide, a 6x7 IT-8 calibration target, two masking sheets, a DVD case with the SilverFast serial, a LaserSoft SilverFast DVD and a Plustek setup CD, and seven film holders:

| Holder | Format | Capacity |
|---|---|---|
| A | 35 mm mounted slides | 5 |
| B | 35 mm strips | 12 frames |
| C | 120/220 6x4.5 | 4 frames |
| D | 120/220 6x6 | 3 frames |
| E | 120/220 6x7 | 3 frames |
| F | 120/220 6x9 | 2 frames |
| G | 120/220 6x12 | 1 frame |

## Controls and connectors

- Front: blue logo LED, power button (with an orange LED), eject button, and the slot for film holders.
- Rear: serial number label, a second slot through which a stuck holder can be pulled out by hand, power input, USB-B port, and a cover over the rear slot and connectors.
- Power button: a short press turns the scanner on or wakes it from standby; holding it for 3 seconds turns it off.

## LED states

| Blue logo LED | Orange power LED | Meaning |
|---|---|---|
| on | off | on, normal operation |
| on | blinking | holder ejected, ready to be removed |
| off | on | standby |
| off | off | off, or no mains power |

## Film holders

Film goes in emulsion side (the dull side) down, aligned to the end marked with a white square and arrow, which leads into the scanner. Each holder has a label on its top side that must face up. Masking sheets cover empty frames in the 35 mm strip holder. The 120 holder has adjustable frame masks.

## Operation

- Power comes from the external adapter; the computer connects over USB-B.
- The scanner pulls an inserted holder in by itself, but only while USB is connected. It needs roughly 35 cm of free space in front because the holder travels out of the front during a scan.
- The holder should slide in without force.

## Software (as shipped in 2012)

- Supported systems at the time: Windows XP, Vista, 7 and 8; Mac OS X 10.5 to 10.8 on Intel. 2 GHz CPU, 2 GB RAM (4 GB recommended), 10 GB disk.
- Windows: the setup CD's `install.exe` installs Plustek's driver (an unsigned driver warning has to be accepted). The driver can also be installed by hand from Device Manager by pointing it at the CD. SilverFast is installed separately from its DVD (`InstallPilot.exe`, SilverFast 8.0.0r1) and unlocked on first start with name and serial.
- Mac OS X: the CD contains a "Mac Driver" disk image with a standard installer package ("Film Scanner Setup") that needs an administrator password and a restart. SilverFast comes from its DVD ("SilverFast InstallPilot", package "Install SilverFast 8 (Plustek)").
- Plustek ships no scanning application of its own; SilverFast is the front end.

## Notes for the driver project

- The firmware has a standby mode (blue off, orange on) and wakes on the power button. On the test Pi the scanner dropped off the bus about 5 minutes after waking when no host software talked to it (`doc/hardware/usb.md`).
- The firmware checks the USB connection before it pulls a holder in.
- Hypothesis from the 35 cm clearance: the holder moves through a fixed lamp and sensor during a scan.
