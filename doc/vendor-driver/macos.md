# Plustek macOS driver

Static notes on `OpticFilmOF120_V3100_12L.dmg` (V3.1.0.0, built 2023-06-20). Nothing was executed. Unpacked with 7-Zip 23.01: dmg (HFS+) → `20230620-Plustek OpticFilm 120_V3.1.0.0.pkg` (xar) → `Payload` (gzip, cpio). Extracted files live in `work/extracted/mac-V3100-payload/` (untracked); `work/extracted/mac-scanapi` is a symlink to the framework directory.

## Layout

The package installs one framework twice, under `/Library/Application Support/LaserSoft Imaging/SilverFast 9/Drivers/Plustek/` and `/Library/Application Support/LaserSoft Imaging/SupportFiles/Plustek/`:

- `PLK_A120.framework/Versions/A/ScanApi`: universal Mach-O shared library (x86_64 and arm64), bundle id `com.plustek.ScanApi`, version 1.4.27.4.0. SilverFast loads it; it is the macOS counterpart of the Windows `Scanapi.dll` and drives the USB device from user space (no kernel extension).
- `Resources/ScanInfoVID_<vid>_PID_<pid>.plist`: one scanner configuration per supported model, 28 files. `ScanInfoVID_07B3_PID_1406.plist` and `ScanInfoVID_07B3_PID_1406-new1440.plist` are the OpticFilm 120. Other IDs in the same framework include `07b3:1436` (OpticFilm 135i), `07b3:1825` (8200i SE), `07b3:1824` (8100), `07b3:181f` (8300i SE) and two `20ec:` devices.

## Symbols

Unlike the Windows DLL, `ScanApi` keeps its C++ symbol names (about 10,000 symbol strings). Classes relevant to this project:

- `CIOUSB`: the USB transport. Register access (`ReadReg`, `WriteReg`, `ReadRegs`, `WriteRegs`, `ReadRegBit`, `WriteRegBit`, `SetRegAddr`), bus access (`AHBWriteAddr`, `APBReadData`, `APBWriteAddr`, `APBWriteData`), bulk and SRAM transfers, AFE access (`ReadAfe`, `WriteAfe`, `WriteAllAfe`), interrupt endpoint (`InitInterrupt`, `ReadInterrupt`, `GetInterruptVal`, `ReadButtonID`), device discovery (`FindDevice`, `FindFirst`, `GetPid`, `Bcd`, `GetSerialNumber`), `HardwareResetScanner`, self tests (`AsicSelfTest`, `SdramSelfTest`, `FlashSelfTest`), and a serial flash API over the ASIC's SPI master: `SPI_init`, `SPI_WriteTxData`, `SPI_ReadRxData`, `SPI_ReadBusData`, `SPI_WriteBusData`, `SFlash_RDID` (JEDEC ID), `SFlash_Read`, `SFlash_Write`, `SFlash_WREN`, `SFlash_WRDI`, `SFlash_ChkWIP`, `SFlash_SectorErase`, `SFlash_BlockErase`, `SFlash_ChipErase`, `SFlash_Erase`.
- `CGL128` (also `CGL125`, `CGL126`, `CGL846`): one accessor per register field, named like Genesys datasheet fields (`SCANRESET`, `MOTORENB`, `LAMPPWR`, `LAMPTIM`, `DPISET`, `STRPIXEL`, `ENDPIXEL`, `LPERIOD`, `STEPNO`, `FEEDL`, `GPIO1` to `GPIO32`, `GPOE1` to `GPOE32`, `HOMESNR`, `EPROMSEL`, `SPI_MOT`, ...). Decompiling these gives the GL128 register map with field names.
- `CAsic::ReadFromNVRAM`, `CScan::GetSerialNumberInfo`, `CScan::WriteShadingDataToFlash`, `CScan::GetShadingAddrSizeFromFlash`, `CScan::GetCounterAddrSizeFromFlash`, `CScan::DumpAllRegFromAsic`, `apiUpgradeFirmware(void*, unsigned int, unsigned int, bool)`, `apiGetDeviceSerialNumber`.

So the host can reach a serial flash on the scanner board through the ASIC. Reading its JEDEC ID and contents is a non-destructive way to see what the board stores, and is the main lead for where the USB identity lives (`doc/work/0007-identity-and-flash.md`).

## The OpticFilm 120 configuration plist

`ScanInfoVID_07B3_PID_1406.plist` holds the complete model configuration the engine uses:

- `0`: base64 blob of ASIC register address/value pairs (initial register set; starts `01 22 02 78 03 20 04 02 05 c8 ...`).
- Register patches keyed by register and mask (`30.0f`, `31.80`, `33.02`, `37.20`, `3b`, `7e`, ...).
- `AHBClock` 60, `SystemClock`, `SENSORSPEED`, `AfeReadReg 0x0050,0x0107,0x0108`, `AfeWriteReg 0x0051,0x005d,0x005e` (AFE accessed through ASIC registers, as pyopticfilm also found).
- Geometry and resolution: `PhysicalDpi 10600,300`, `PseudoDpi 10600,600`, `MinDpi`, `MaxPaperLength`, `FilmLoaderOrigin`, `FilmLoaderSize`, `Frame_0`, `Frame_1`, ..., per-resolution blocks (`5300`, `-10600`, `600`, `150`) with exposure, shading (`LineDark`, `PixelDark`, `LineGain`, `PixelGain`, `WholeLineShading`) and motor settings.
- Infrared: `EnableIR`, `Enable_IR_Scaling`, `flash_addr_Postive_IR_Scaling 0,0x00000,0x00040`.
- Power: `StandbyOffTime 15`, `StandbyReg`, `WarmUpTime`, `FastWarmUpTime 45`, `LampOffTime`.
- `FlashRAM 1`: the OpticFilm 120 configuration marks the flash as present.

`-new1440` differs from the base file in a handful of values (`0x31,0x04` vs `0x31,0x80`, `110,240,440` vs `110,240,220`, `6675` vs `6880` in two frame definitions, register patches `31.80` and `34.80` absent, `StandbyReg` disabled). What selects it ("1440" may be a sensor or board revision) is not known yet.

## Open questions

1. How `FindDevice` matches devices (only `07b3`, or also by `Bcd`), and how the engine chooses between `1406` and `1406-new1440`.
2. The USB request encoding of every `CIOUSB` primitive, especially the SPI and serial flash operations.
3. What the OpticFilm 120 keeps in flash (IR scaling at `0x00000`, serial number, shading, firmware, USB identity?) and what `apiUpgradeFirmware` writes.
