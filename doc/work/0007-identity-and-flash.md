# 0007 Find where the USB identity and firmware live

Status: in progress

The unit enumerates with Genesys defaults (`05e3:0103`) instead of Plustek's `07b3:1406` (`doc/research.md`). Find out what on the board holds the identity (and any firmware or calibration data), why it is no longer used, and whether it can be restored.

Steps:
- [x] Read the macOS engine with Ghidra instead of `Scanapi.dll`: it carries C++ symbol names. Results in `doc/protocol/serial-flash.md`, `usb-requests.md`, `gl128-registers.md`. `apiUpgradeFirmware` is a stub there.
- [x] Probe the unit read-only (`doc/hardware/usb.md`, "Read-only probe"). The ASIC answers register reads.
- [x] Dump the serial flash over USB (2026-10-14, `doc/hardware/flash-dump.md`): only the IR record, no identity, no CounterControl fingerprint.
- [ ] Find out whether the board carries a serial EEPROM on the ASIC's EEPROM interface (`EPROMSEL`, `CAsic::ReadFromNVRAM`): board photos, and the register sequence for a read over USB.

Any write to the scanner's non-volatile storage requires the owner's explicit approval for that specific write.
