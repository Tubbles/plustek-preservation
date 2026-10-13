# 0007 Find where the USB identity and firmware live

Status: in progress

The unit enumerates with Genesys defaults (`05e3:0103`) instead of Plustek's `07b3:1406` (`doc/research.md`). Find out what on the board holds the identity (and any firmware or calibration data), why it is no longer used, and whether it can be restored.

Steps:
- [x] Read the macOS engine with Ghidra instead of `Scanapi.dll`: it carries C++ symbol names. Results in `doc/protocol/serial-flash.md`, `usb-requests.md`, `gl128-registers.md`. `apiUpgradeFirmware` is a stub there.
- [x] Probe the unit read-only (`doc/hardware/usb.md`, "Read-only probe"). The ASIC answers register reads.
- [ ] Dump the serial flash over USB with `tools/pi/flash_dump.py` (SPI init and address writes only, needs the owner's go-ahead), then look for the identity, the CounterControl fingerprint at address 0 and the IR record.
- [ ] Board photos from the owner (approved, "when needed") to identify the flash chip, if the USB dump is not enough.

Any write to the scanner's non-volatile storage requires the owner's explicit approval for that specific write.
