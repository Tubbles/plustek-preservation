# 0007 Find where the USB identity and firmware live

Status: in progress

The unit enumerates with Genesys defaults (`05e3:0103`) instead of Plustek's `07b3:1406` (`doc/research.md`). Find out what on the board holds the identity (and any firmware or calibration data), why it is no longer used, and whether it can be restored.

Steps:
- [x] Read the macOS engine with Ghidra instead of `Scanapi.dll`: it carries C++ symbol names. Results in `doc/protocol/serial-flash.md`, `usb-requests.md`, `gl128-registers.md`. `apiUpgradeFirmware` is a stub there.
- [x] Probe the unit read-only (`doc/hardware/usb.md`, "Read-only probe"). The ASIC answers register reads.
- [x] Dump the serial flash over USB (2026-10-14, `doc/hardware/flash-dump.md`): only the IR record, no identity, no CounterControl fingerprint.
- [x] Find out whether the board carries a serial EEPROM on the ASIC's EEPROM interface (`EPROMSEL`, `CAsic::ReadFromNVRAM`): board photos (2026-10-14, `doc/hardware/board.md`) show an Atmel AT93C46D as U19 next to the ASIC, the part family `ReadFromNVRAM` is written for. The register sequence for a read over USB is `tools/pi/eeprom_read.py` (`doc/protocol/serial-eeprom.md`).
- [x] Read U19 over USB with `tools/pi/eeprom_read.py` (2026-10-14 22:08 UTC, `doc/hardware/eeprom-read.md`): every word `0000`, the data registers do not follow the address. The USB route stops here.
- [ ] Read U19 in circuit with an SOIC-8 clip on the Pi's GPIO (hardware purchase, owner's decision). The same clip can watch the Microwire lines at power-up to see whether the ASIC reads the chip.
- [ ] Find out what the 8051 MCU (U11) does. It is the only other programmable part on the board.

Any write to the scanner's non-volatile storage requires the owner's explicit approval for that specific write.
