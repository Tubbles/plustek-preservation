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

## Device discovery and model selection

From the x86_64 slice of `ScanApi`, analysed with Ghidra (`../../tools/ghidra/README.md`). Addresses are offsets in that slice. The USB request encodings are in `../protocol/usb-requests.md` and `../protocol/serial-flash.md`.

### Which devices the engine opens

- `CRegistry::GetPrereference` (`0x08a930`) reads `Resources/Prereference.plist`, dictionary `ScannerID`: `VendorID` 1971 (`0x07b3`), `ProudctID` 5126 (`0x1406`), `SupDevNum` 2, `VendroString` "Plustek", `ProductString` "OpticFilm 120_Scanner". The other keys there (`ProudctID-30D`, `ProudctID-8100`, ...) have suffixed names and are not read. A second product ID (`ProudctID2`) is read only when the first one is `0x143d`, `0x130d`, `0x181b`, `0x1301`, `0x130c` or `0x1320`, so for this package it stays 0 (`CRegistry::CRegistry`, `0x089dc0`).
- `CIOUSB::FindFirst` (`0x038f00`) calls `CIOUSB::FindDevice` (`0x0f05b0`), which asks IOKit for `IOUSBDevice` services matching `idVendor` and `idProduct`, once per `SupDevNum`: first with `ProudctID`, then with `ProudctID2`.
- `CIOUSB::DealWithDevice` (`0x0efe40`) opens each match, checks the vendor ID again and the product ID against both values, then records bcdDevice (`GetDeviceReleaseNumber`, stored at `CIOUSB+0x12`) and the IOKit property `USB Serial Number` without checking either. It selects the first configuration and hands the interfaces to `CIOUSB::DealWithInterface` (`0x0efa10`).

So matching uses VID and PID only. bcdDevice, the manufacturer and product strings and the string indices play no part. A unit reporting `05e3:0103` is not opened. Editing `Prereference.plist` and renaming the configuration file would get it opened, but two code paths compare the PID with `0x1406` and `0x1440` (see below), so the engine would behave differently there, for example polling the interrupt endpoint instead of the wIndex `0x21` probe. Not tested.

### Which configuration file

`CRegistry::OpenRegistry` (`0x08acd0`) builds the file name from the matched VID and PID. Only when the USB serial number string equals `A20210507` (case-insensitive) does it load `ScanInfoVID_%04X_PID_%04X-<serial>.plist`; in every other case, and when the device has no serial number string, it loads `ScanInfoVID_%04X_PID_%04X.plist`. The OpticFilm 120 has no serial number string (iSerialNumber 0), so the engine always loads `ScanInfoVID_07B3_PID_1406.plist`.

`ScanInfoVID_07B3_PID_1406-new1440.plist` is never loaded by this code: the string `new1440` occurs in neither slice. The change log `Resources/Modify` says "20221118 1.4.27.3.0 ... Add Pid:1440 new OF120 Scanboard", and the engine treats PID `0x1440` like `0x1406` in two places (`CIOUSB::Interrupt`, `0x0f2010`; `CScan::DeleteShadingFiles`, `0x0e15ff`). So `-new1440` is presumably the configuration for a newer OpticFilm 120 board that enumerates as `07b3:1440` *(inference)*. With this package such a unit would not be found, since `Prereference.plist` lists only `0x1406` and there is no `ScanInfoVID_07B3_PID_1440.plist`. Whether the installer renames files was not checked.

### Which chip class

Every `CAsic::_<FIELD>` dispatcher (268 of them, all with the same structure, for example `CAsic::_DPIHW` at `0x00ef70`) picks the chip class from `CIOUSB::Bcd()`:

| bcdDevice | Class |
|---|---|
| ≥ `0x0704` | `CGL128` |
| `0x0703` | `CGL125` |
| `0x0702` | `CGL126` |
| `0x0600` to `0x0701` | `CGL846` |
| < `0x0600` | none (the accessor returns 0) |

The OpticFilm 120 reports bcdDevice `0x0702`, so **the A31 engine uses `CGL126`**, matching the Windows folder name `DRV_U_GL126_A31`. Plustek's class names therefore do not follow SANE's chip names: SANE calls bcdDevice `0x0702` a GL128. `CScanApi::Register` would replace bcdDevice with plist key `BcdDevice` if that were set; the OpticFilm 120 plist has none.

### What the engine sends at open

`CScanApi::Register` (`0x01da80`) for the OpticFilm 120, in order, with the issue #151 capture steps (`../protocol/of120-capture-151.md`, "Open") where order and registers match *(inference: the capture comes from the Windows driver, so the pairing is by shape, not by shared code)*:

| macOS engine | Capture step |
|---|---|
| `CIOUSB::InitInterrupt`: read wIndex `0x26fe` | 1 |
| `CScanApi::SoftwareResetScanner` (`0x0338a0`): reads `LAMPPWR` and `XPASEL`, writes `SCANRESET`, then the register blast (`WriteAllReg`), system and AHB clock (`0x8c` index `0x10` and `0x13`), `ENBDRAM` off, `RFHSET`, `ENBDRAM` on, `SPI_init`, `SFlash_RDID`, another `WriteAllReg` and all AFE registers | 2 to 5, and C1 to C3 of set C |
| `WriteAllReg`, clocks, `ENBDRAM`/`RFHSET`/`ENBDRAM` again (bcdDevice ≥ `0x400`) | |
| `SPI_init`, `SFlash_RDID`, `ReadIRScalingInfo` (flash address 0, 64 bytes) | C1 to C5 |
| `CAsic::WaitMotorStop` (`0x056d80`): polls `MOTORENB` | 7, reads of `0x101` |
| `CAsic::LampOn(false)` (plist `LampType` 1) | 8, `0x03 = 0x00` |
| `WriteAllReg`, AFE software reset, `WriteAllAfe` | 9, eight AFE writes |
| `CAsic::LoaderEjectSel(true)` (`0x06b140`): set bit 1 of `0x36` (plist `LoaderEjectSwitchIO 0x36,1`), then read-modify-write of `0x33` bit 1 (`LoaderEjectSwitch 0x33,0x02,1`) | 10 and 11 |
| `CIOUSB::IsHispeed`: read wIndex 0 | 12 |
| `CAsic::StandbyModeSel(true)`, 10 ms sleep, `StandbyModeSel(false)`: clear, then set bit 7 of `0x31` | 13 (`0x31`: `0xbe` → `0x3e` → `0xbe`, 13 ms) |

The macOS engine sends the blast, the clock set-up and `SPI_init` twice (once in `SoftwareResetScanner`, once in `Register`), RDID three times (`../protocol/serial-flash.md`, "When the engine touches the flash at open") and a second block of register, AFE and clock writes after taking its scanner lock again. The capture has each only once, so Plustek's Windows driver differs in detail. The order of the capture's open sequence matches the second half of `Register`.

### Standby

Plist: `StandbyReg = 0x31,0x80` and `Add-On/StandbyOffTime = 15` (minutes).

- `CAsic::StandbyModeSel(true)` (`0x061ac0`) clears bit 7 of register `0x31`; `StandbyModeSel(false)` sets it. `CAsic::IsStandbyMode` (`0x061d60`) reports standby while the bit is clear. `CScanApi::StandbyModeControl` (`0x038e50`) wraps it and records the state.
- At open, `Register` calls `StandbyModeSel(true)`, waits 10 ms and calls `StandbyModeSel(false)` (calls at `0x01e784` and `0x01e7a6`). This is the 13 ms low pulse on bit 7 in the capture (`../protocol/of120-capture-151.md`, frames 127 to 138). Later in the open it calls `StandbyModeControl(false)` again (`0x01ef52`).
- `CScanApi::InitStandbyModelOffTimeInfo` (`0x022ee0`) arms a host timer of `(StandbyOffTime − 5)` minutes (10 minutes here, at least 0) and `CNotify` ticks it every 5 s. `CScanApi::SetStandbyOffTime` (`0x0387a0`) counts idle time while no scan runs; when the timer expires it calls `StandbyModeControl(true)` and logs "scanner set into standby mode in 5 min". A running scan resets the idle count. When the film holder is ready (`LoaderReadyReg 0x31,0x04`) or sits on the home sensor while the scanner is in standby, the engine leaves standby (`StandbyModeControl(false)` sets bit 7) and resets the count.
- The only keep-awake action in the engine is keeping bit 7 set. Before the host timer expires, `SetStandbyOffTime` reads the bit on each 5 s tick and sets it when it is clear. `CScanApi::StartScan` (`0x027c50`) and `CScanApi::DoCalibration` (`0x034120`) call `StandbyModeControl(false)` as well. `CScanApi::TestUnitReady` (`0x0232f0`) has such a call too, but behind bit 0 of `CNotify::m_Notice`, which none of the three decompiled writers of that field sets (`../protocol/playbook.md`, "Standby", part 2), so on the tick path it sends nothing. There is no periodic pulse and no other request for this.
- At close, `CScanApi::Unregister` (`0x01f470`) switches the lamp off with `MyWriteReg` (which writes register 3 = 0, see `../protocol/usb-requests.md`) and calls `StandbyModeControl(true)` (`0x01f7dc`), which explains the final clear of bit 7 in the capture.
- The plist sets bit 7 of `0x31` and bit 7 of `0x34` together, with the register patches `31.80` and `34.80` (value `0x80` each) on top of the base table (plist key `0`), which has `0x31 = 0x7c` and `0x34 = 0x00` (`CRegistry::ReadKey`, `0x08b090`, applies a `reg.mask` key as `(old & ~mask) + value`). In `CGL126`, `0x34` bit 7 is `GPOE8`, the output enable of `GPIO8` (`../protocol/gl128-registers.md`). The `-new1440` plist has neither patch.

The owner's unit read `0x31 = bc` (bit 7 already set) and still left the bus about 5 minutes after waking (`../hardware/usb.md`, "Standby" and "Read-only probe"). So a clear bit 7 at power-on does not explain the drop. One reading that fits: the standby line is not driven until `GPOE8` is set, so the value in bit 7 has no effect on a unit no driver has initialised *(inference)*. The owner's `0x36 = 00`, against `0xfc` written by the driver in the capture, suggests the output enables start at 0 after reset *(inference)*. The flash dump run read `0x34 = 00` on the owner's unit, so `GPOE8` is clear there (`../hardware/flash-dump.md`).

## Open questions

1. ~~How `FindDevice` matches devices~~: VID and PID only, see "Device discovery and model selection". How a `07b3:1440` board would be configured is open.
2. ~~The USB request encoding of every `CIOUSB` primitive~~: `../protocol/usb-requests.md` and `../protocol/serial-flash.md`.
3. ~~What the OpticFilm 120 keeps in flash~~: only the infrared scaling record at address 0, which an `apiCounterControl` reset would erase with the rest of the first 64 KiB; `apiUpgradeFirmware` is a stub (`../protocol/serial-flash.md`). Where the USB identity comes from is still open: the host code never handles it.
