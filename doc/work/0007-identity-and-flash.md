# 0007 Find where the USB identity and firmware live

Status: in progress

The unit enumerates with Genesys defaults (`05e3:0103`) instead of Plustek's `07b3:1406` (`doc/research.md`). Find out what on the board holds the identity (and any firmware or calibration data), why it is no longer used, and whether it can be restored.

Steps:
- Disassemble `Scanapi.dll` (Ghidra): which chip class the A31 engine uses, what `apiUpgradeFirmware` and the flash routines do, whether they apply to the OpticFilm 120, which USB requests they send.
- Read the macOS driver (needs `p7zip-full`), which may carry symbol names.
- Probe the unit read-only once the capture decode (0008) gives a safe request set.
- Board photos from the owner (approved, "when needed") to identify the flash or EEPROM chip.

Any write to the scanner's non-volatile storage requires the owner's explicit approval for that specific write.
