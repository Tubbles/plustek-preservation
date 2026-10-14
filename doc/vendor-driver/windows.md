# Plustek Windows driver

Static notes on the Windows driver package `OpticFilmOF120_V5020_12L.zip` (V5.0.2.0, 2015). Nothing was executed. Extraction: `unzip`, then the InstallShield cabinets `data1.hdr`/`data1.cab`/`data2.cab` with `unshield` 1.6.2 built from <https://github.com/twogood/unshield> into `work/build/` (no system install). Extracted files live in `work/extracted/` (untracked).

## Layers

| Component | Role (from INF and file names) |
|---|---|
| `usbscan.sys` | Microsoft's generic USB still-image kernel driver. Gives user space a handle with bulk and control pipes. |
| `A31U.inf` / `A31U_x64.inf` | Binds `USB\VID_07B3&PID_1406` to `usbscan.sys` and registers the WIA driver. Device name "Film Scanner(A31)". |
| `WIAA3103.dll`, `PkWiaDrv20_A31*.dll`, `PkWiaScanUI*.dll` | WIA micro driver and UI glue. No hardware specific strings. |
| `MidrvA31.dll` | Small (57 KB) helper, no hardware specific strings. |
| `DRV_U_GL126_A31/Scanapi.dll` (1.4 MB, 32 bit) and `DRV_U_A31_x64/Scanapi_x64.dll` (1.7 MB) | The scanner engine: all hardware logic lives here. |
| `DRV_U_GL126_A31/module.ini` | `module=A31`, `scannerid=1971,5126` (decimal for `07b3:1406`), `Company=Plustek`, `VXDPATH=SOFTWARE\Film Scanner\A31\VxD`. |

## What `Scanapi.dll` contains (strings)

- One codebase for several Genesys chips: C++ classes `CGL125`, `CGL126`, `CGL128`, `CGL846` (RTTI names). Plustek's folder name calls the OpticFilm 120 engine "GL126" while SANE's chip probe says GL128 for bcdDevice `0x0702`. The chip is chosen by bcdDevice, see "Disassembly" below.
- Device lookup by VID/PID: `HKEY_LOCAL_MACHINE\%s\VID_%04x&PID_%04x`, `ScanApi_%04x_%04x.ini`. How the engine matches devices is in "Disassembly", "Device discovery and configuration".
- Firmware and flash handling: `apiUpgradeFirmware`, `apiGetDeviceSerialNumber`, `CheckFlashRam`, `FlashRAM`, `FlashSize`, "Are you sure to erase flash address from 0x%08x to 0x%08x ?", "Are you sure to test read/write flash ?", "Chip/Sector Erase start/finished", "Flash data compare OK !", `SaveShadingToFlash`, and a family of `flash_addr_*` names (`flash_addr_negative_scan`, `flash_addr_positive_scan`, `flash_addr_Postive_IR_Scaling`, many ADF and flatbed ones). Some of these clearly belong to document scanners sharing the codebase (ADF, duplex, seven segment display), so their presence says nothing yet about the OpticFilm 120 board.
- Host side files: `filmholderposition.dat`, `autoposition.dat`, `Global\%d%dserialnumber.dat`.
- "Register : read data from f/w -- Reg = 0x%04x ..." and "waiting data ready interrupt from f/w": some models run firmware that the engine talks to through registers and the interrupt endpoint.

## Disassembly

`DRV_U_A31_x64/Scanapi_x64.dll` of V5.0.2.0 (FileVersion 4.0.0.808, linked 2015-02-13), read with Ghidra 12.1.4 in headless mode (`../../tools/ghidra/README.md`, "Windows engine"). The DLL has no symbols. Function names below come from the engine's log strings (each `api*` wrapper logs its own name), from RTTI (`CUsb`, `CAsic`, `CScan`, `CRegistry`, `CNotify`) or from matching the code against the macOS engine. "macOS `0x......`" gives the counterpart in `macos.md` and `../protocol/serial-flash.md`. Addresses are virtual addresses at the image base `0x180000000`. "No caller" means three checks came back empty: Ghidra's references, a scan of `.text` for `E8`/`E9` relative calls or jumps to the address at every byte offset, and a search of the whole file for a 64-bit pointer to it (`../../tools/ghidra/find_code_references.py`). Each such function's RVA occurs only in its own unwind entry in `.pdata`, except for `WriteIRScalingInfo`, whose RVA value also appears as the RIP-relative displacement of an unrelated load at `0x1800f9415`. Nothing was executed. *(inference)* marks interpretation. Raw outputs are in `work/re-win/` (untracked).

### Engine builds in the Windows packages

| Package | Engine FileVersion | Linked (UTC) |
|---|---|---|
| V5.0.0.2 (`OpticFilm120-V5002_12L.zip`) | 4.0.0.411 | 2013-02-01 |
| V5.0.0.4 (`OpticFilm120-V5004_12L.zip`) | 4.0.0.414 | 2013-03-27 |
| V5.0.1.0 (`OpticFilmOF120-V5010_12L.zip`) | 4.0.0.416 | 2013-08-02 |
| V5.0.2.0 (`OpticFilmOF120_V5020_12L.zip`) | 4.0.0.808 | 2015-02-13 |
| V6.0.0.0 (`OpticFilmOF120_V6000_12L.exe`, a RAR self-extractor, folder `20230628_OpticFilm 120_12L_V6.0.0.0`) | 1.4.16.0 | 2023-04-21 |

Every package carries its own `Scanapi.dll` and `Scanapi_x64.dll` (all ten SHA-256 hashes differ, both bitnesses of a package are linked the same day). `PkWiaDrv20_A31.dll`, `PkWiaDrv20_A31_x64.dll`, `WIAA3103.dll`, `ComScan.exe`, `A31U.inf` and `A31U_x64.inf` are byte-identical in all five packages. V6.0.0.0 also installs `ScanApi_07b3_1406.ini` next to each engine, which only names the registry key (`VxDPath=Software\Film Scanner\A31\VxD`, `InIFlag=0`). The A31 registry values of V6.0.0.0 differ from V5.0.2.0 only in scan geometry (`AREAPAGE`, `LoaderSensorCurve` and one register value under `PositiveIR\Color\5300`), none in a flash, counter or standby key. `engine32.cab` in every package is InstallShield's own engine, not scanner code. The rest of this section describes V5.0.2.0. "V6.0.0.0 engine" at the end lists what was rechecked in the newest build.

### Exports and who calls them

- Exports: `SCANAPI_GetFunctionTable` (`0x1800039c0`) and `ScannerDriverEntry` (`0x18003c930`, an older style entry). `SCANAPI_GetFunctionTable` fills a table of 43 pointers at `0x18012ba00` once and returns it. By log string, `apiUpgradeFirmware` (`0x1800032c0`) sits at table offset `0xf8` (slot 31), `apiGetCounterInfo` (`0x180003530`) at `0x128` (slot 37) and `apiCounterControl` (`0x1800035b0`) at `0x130` (slot 38).
- `PkWiaDrv20_A31_x64.dll` (WIA 2.0 driver) loads the engine named in the registry, keeps the table pointer at object offset `0x748` (`0x1800047a0` in that DLL) and calls only slots 3 to 9, 27, 33, 39, 41 and 42. Slots 41 and 42 open and close a session from a device handle (`0x1800037a0` and `0x180003900` in the engine). The 32-bit `PkWiaDrv20_A31.dll` calls the same slots (pointer at object offset `0x718`).
- `WIAA3103.dll` (WIA 1.0 micro driver) does not load the engine itself. It creates COM class `{28FC629B-276F-4D7D-9A67-E748A7E036DB}` (`0x180003cc0` in that DLL), which `ComScan.exe` registers as "CoScannerCommander Class". The 32-bit `ComScan.exe` resolves the table (`0x00401b81`) and calls slots up to 24 only (table offset `0x60`).
- `MidrvA31.dll` and `WIAA3103.dll` also name `SCANDRV.DLL`. Only V5.0.0.2 to V5.0.1.0 ship it (`DRV_U_GL126_A31/scandrv.dll`, 32 bit, version 4.0.0.2, linked 2011-08-30): it exports `ScannerCommander` and resolves the engine's older export `ScannerDriverEntry`, not the function table. In V5.0.2.0 that export leads to `0x18003de60`, which does not reach `CounterControl`. Its paths to a flash erase or write go through functions gated by keys the A31 lacks (question 1).
- So no Plustek component in the packages calls `apiCounterControl`, `apiGetCounterInfo` or `apiUpgradeFirmware`. The packages contain no TWAIN data source, updater, tray tool or service. Whether third-party software (SilverFast, VueScan) loads `Scanapi.dll` and calls those slots was not checked.

### Transport

- `CUsb` (RTTI name, vftable set in its constructor `0x1800fbf80`) is the counterpart of the macOS `CIOUSB`. It sends every request as a `DeviceIoControl` to `usbscan.sys`. The codes match `usbscan.h` (`CTL_CODE(0x8000, 0x800 + n, METHOD_BUFFERED, FILE_ANY_ACCESS)`, <https://raw.githubusercontent.com/reactos/reactos/master/sdk/include/ddk/usbscan.h>): `0x80002004` `IOCTL_CANCEL_IO` (`0x1800fdc10`), `0x80002008` `IOCTL_WAIT_ON_DEVICE_EVENT` on the `\3` interrupt pipe (`0x1800fdc90`, `0x1800fdfc0`), `0x8000200c` `IOCTL_READ_REGISTERS`, `0x80002010` `IOCTL_WRITE_REGISTERS`, `0x80002018` `IOCTL_GET_DEVICE_DESCRIPTOR` (`0x1800fc810`, `0x180104840`) and `0x80002020` `IOCTL_GET_USB_DESCRIPTOR` (`0x1800fc940`). `FindScalars` finds no `IOCTL_SEND_USB_REQUEST` (`0x80002024`), `IOCTL_RESET_PIPE` (`0x8000201c`) or `IOCTL_GET_CHANNEL_ALIGN_RQST` (`0x80002014`).
- `ControlRead(wValue, wLength, buffer, wIndex)` (`0x1800fd1a0`) and `ControlWrite` (`0x1800fd300`, macOS `CIOUSB::ControlWrite`) fill an `IO_BLOCK` {uOffset = wValue, uLength = wLength, pbyData, uIndex = wIndex}. The engine never chooses bRequest. Microsoft documents that usbscan sends `(uLength > 1) ? 0x04 : 0x0C` with bmRequestType `0xc0` or `0x40` (<https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_write_registers>, `.../ni-usbscan-ioctl_read_registers>`). That is the `0x0c`/`0x04` split of the issue #151 capture, so the ASIC indeed ignores bRequest (the macOS engine sends `0xa0`).
- For bcdDevice ≥ `0x200`, `ControlWrite` retries a write up to 10 times, and after each write reads one byte with wValue `0x8e`, wIndex `0x20` (up to 10 attempts) until bit 0 is set. This is the "link check" read returning `0x55` after nearly every write in the capture (`../protocol/usb-requests.md`, "Common rules").
- `MyWriteReg` (`0x1800fec10`) has the same defect as on macOS: it sends the two bytes of the 16-bit register number and never the value.
- `ReadReg` (`0x1800fe820`), `ReadRegs` (`0x1800feaa0`), `WriteReg` (`0x1800fed80`) and `WriteRegs` (`0x1800ff090`) take a chip argument the macOS build lacks. Chip 0 uses the macOS framing (wValue `0x83` and `0x8e`, wIndex 0 and `(reg << 8) | 0x22`). Chip 1, a "slave" ASIC, uses wValue `0x8b` wIndex `0x0a` for writes and wValue `0x8a` wIndex `(reg << 8) | 0x0a` for reads, and keeps its own register shadow. The slave paths sit behind configuration key `Slave` (getter `0x180031d10`, checked for example in `0x1800c3a30`, `0x180046590`, `0x1800ffcf0` and in `Register`, which then copies master registers 1 to `0x11f` to the slave with `0x1800ff7a0`). The A31 configuration has no `Slave` key. Not every call site that passes the chip argument from a variable was traced *(inference that all are gated)*.

### Device discovery and configuration

- Discovery (`FindFirst` `0x180031ef0`, `FindNext` `0x180031f30`, both into `0x1800fc4b0`) enumerates `GUID_DEVINTERFACE_IMAGE` `{6bdd1fc6-810f-11d0-bec7-08002be2092f}` with `SetupDiGetClassDevsA(DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)` on Windows 2000 and later, otherwise `\\.\Usbscan0` to `\\.\Usbscan127`. It reads VID, PID and bcdDevice of each device with `IOCTL_GET_DEVICE_DESCRIPTOR` (`0x180104840`, stored at `CUsb+0x78`, `+0x7a`, `+0x7c`). So the engine only sees devices that `usbscan.sys` is bound to, and the INF binds only `USB\VID_07B3&PID_1406`.
- The match (`0x18008c270`) accepts a device when a file `ScanApi_<vid>_<pid>*.ini` exists next to the engine, or when the configured VxD key (`SOFTWARE\Film Scanner\A31\VxD`) has a subkey named `Vid_xxxx&Pid_xxxx` with that VID and PID (list built by `0x180087830`), or when that VxD key has a non-empty default value, in which case every device matches. bcdDevice and strings play no part. Configuration then comes from the ini file (`0x18008e520`, which copies it to `CSIDL_APPDATA\Plustek\<module>\`) or from the registry key of the matched entry (`0x1800880c0`). A serial-suffixed key (`VID_%04x&PID_%04x-%8x`) is used only when a number derived from the serial equals one of six hard-coded values (`0x20080527`, `0x20090921`, `0x20100318`, `0x20100611`, `0x20110111`, `0x20110214`).
- Consequence for a unit reporting `05e3:0103`: the shipped INF does not bind it, so the engine never sees it. With `usbscan.sys` bound to it by other means, a registry subkey `Vid_05e3&Pid_0103` holding the A31 values, or a matching ini file, would get it opened *(inference from the match code; not tried)*. `0x05e3`, `0x1406` and `0x1440` occur in no instruction operand (`FindScalars`). `0x0103` occurs only as a buffer length (259) and as `STILL_ACTIVE` after `GetExitCodeThread`. `0x07b3` occurs once, as an argument of `ConnectPOD` for the external `EasyPod.dll` (`0x1800266d0`, no caller).
- The chip class dispatch uses the same bcdDevice boundaries as macOS (seen in the `EPROMSEL` dispatcher `0x18006e730`: ≥ `0x704`, `0x703`, `0x702`, `0x600` to `0x701`), so bcdDevice `0x0702` selects the same class slot that is `CGL126` on macOS (`macos.md`, "Which chip class"). The Windows class name of that slot was not tied to RTTI *(inference)*.
- Configuration source for the A31: registry `HKLM\SOFTWARE\Film Scanner\A31\VxD\VID_07b3&PID_1406` and its `Add-On` subkey, written by the installer from the InstallShield registry table in `data1.hdr`. Values that matter here: `FlashRAM = 1`, `FlashSize = 64,16`, `StandbyReg = 0x31,0x80`, `LoaderReadyReg = 0x31,0x04`, `Add-On\StandbyOffTime = 15`, `Add-On\flash_addr_Postive_IR_Scaling = 0,0x00000,0x00040`, `Enable_IR_Scaling = 5300,1322,11328,751,1381,11314,757` (the macOS plist has other numbers). There is no counter key (`RftCounterScan`, `PosCounterScan`, `NegCounterScan`, `AdfCounterPad`, `AdfCounterRoller`, `ShtCounterScan`), no `SaveShadingToFlash`, no `Slave` and no seven segment key. Unlike the macOS plist, `FlashSize` is set.
- The engine reads the serial number from the USB string at iSerialNumber (`0x1800fc940`, `IOCTL_GET_USB_DESCRIPTOR`) without checking for index 0, or from the named shared memory `Global\%d%dserialnumber.dat` (`CreateFileMappingA` on the page file, `0x180029ff0`, so not a file on disk). With iSerialNumber 0 it would ask for string 0, the language list *(inference)*. `apiGetDeviceSerialNumber` (`0x180003320`) returns that value, unlike the macOS stub.

### Question 1: firmware update and flash writes

- `apiUpgradeFirmware` (`0x1800032c0`, macOS `0x0350e0`) is the same stub as on macOS: it logs, returns `0xffffffa2` without an open session and `0xffffffa0` otherwise, and sends nothing.
- Flash primitives on `CUsb`, same requests as macOS (`../protocol/serial-flash.md`): `SPI_init` `0x180101f50` (wValue `0x8b`, wIndex 7 and 9), memory read `0x180102070` and write `0x180102160` (wIndex `0x0b` address, then `0x8a`/`0x8b` wIndex `0x0c`, at most 64 bytes, used for SDRAM, gamma and shading tables, which are volatile *(inference)*), `RDID` `0x180102250`, `WREN` `0x1801023e0`, `WRDI` `0x180102480`, status poll `0x180102520`, `ChipErase` `0x180102650` (wIndex `0x10`, wLength 0, request at `0x180102757`), `BlockErase` `0x180102770` (wIndex `0x11`, `0x1801027c6`), `SectorErase` `0x1801027e0` (wIndex `0x12`, `0x180102a08`), `Erase(addr, size)` `0x180102a30` (4 KiB sectors), `Write` `0x180102ab0` (wIndex `0x0b` at `0x180102e44`, 64-byte chunks with wIndex `0x0f` at `0x180102ea2` and `0x180102f1a`), `Read` `0x180102f50`, hardware reset `0x1801039e0` (wIndex 4).
- Every caller of an erase or program primitive:

| Function | Reached from | Gate | Effect on the A31 |
|---|---|---|---|
| `ChipErase` `0x180102650` | no caller | | none |
| `BlockErase` `0x180102770` | `FlashSelfTest` only | | none |
| `FlashSelfTest` `0x180103e50` (macOS `0x0f8410`, a stub there) | no caller | message boxes "Are you sure to erase flash address from 0x%08x to 0x%08x ?" | none. Unlike macOS it is implemented: block or sector erase over `FlashSize[0] × 1024 × FlashSize[1]` bytes (1 MiB with the A31 values), test pattern write, read back, compare. |
| `CounterControl` `0x180022040` (macOS `0x0354e0`) | `apiCounterControl` `0x1800035b0` (call `0x1800035f7`) | open session, `TestUnitReady`, scanner lock | erase and write, see question 2 |
| `GetAllCounterInfo` `0x180023500` | `Register` (`0x180005f26`, `0x18000732d`), which `apiRegister` and `TestUnitReady` call | `FlashRAM` and a counter key | none (no counter key) |
| `WriteScanningCountInfo` `0x180025770` | `0x180011700` (from `apiStartScan` and `apiStopScan`), `DoCalibration` `0x180020950` | counter flags `0x1801285c0` to `0x180128600`, set only by `GetDeviceCapability` `0x1800081f0` and `GetAllCounterInfo` when `FlashRAM` and a counter key are set | none, may send `SPI_init` |
| `WriteAllCountInfo` `0x180025070` | no caller | | none |
| `WriteIRScalingInfo` `0x180030200` (macOS `0x0484f0`) | no caller | `FlashRAM` | none (would erase sector 0 and write 64 bytes) |
| `WriteShadingDataToFlash` `0x1800eb680` | `0x1800c3a30` (`0x1800c7109`), `0x1800cde30` (`0x1800d1043`) | bcdDevice ≥ `0x600`, `FlashRAM`, `SaveShadingToFlash` | none (no `SaveShadingToFlash`, so shading goes to a host file, `0x1800dd770`) |
| `EraseShadingDataOnFlash` `0x1800eae30` | `0x1800e3e10`, which `DoCalibration` calls | `FlashRAM`, `SaveShadingToFlash` | none |
| `AsicSelfTest` `0x180103a20` (register and SDRAM test) | no caller | | none, and it does not touch the flash |

- At open, `Register` (`0x1800051e0`) touches the flash only when `FlashRAM` is set and the host process is not a service. `IsServiceProcess` (`0x1800233e0`) is true in `stiImg.exe`, `svchost.exe`, `stiimage.exe`, `ComScan.exe` and `WIA_Service.exe`, so through the shipped WIA paths the open sends no flash request at all *(inference: the WIA drivers run inside the WIA service host)*. In an application process it sends `SPI_init` once (`0x180005e08`, or `0x180007206` in the second block), `RDID` up to twice (`0x180005e37`, `0x180007235`) and the 64-byte infrared read at address 0 once (`ReadIRScalingInfo` `0x18002fde0`, read at `0x18002fed4`).
- No other non-volatile write exists: the immediate `0x8b` as a register number occurs only in `ReadFromNVRAM` (question 3), and no code writes descriptors or identity (question 4). For the A31 the only reachable flash write is `apiCounterControl`, as on macOS.

### Question 2: `CounterControl`

`CounterControl` (`0x180022040`) has the macOS structure: actions 0 and 1 return counts held in memory, action 2 (counter 0, or counter 0 or 1 for source 3) moves the running count into the total, fills a 64 KiB buffer with `0xff`, puts 0 and the total into words 0 and 1, then calls `Erase(addr, size)` and, if that worked, `Write(addr, buffer, 64)` (32 bytes when bcdDevice is `0x602`). Its only gates are an open session (`0x18012b9c8`), `TestUnitReady` (`0x1800047e0`) and the scanner lock (`0x180007fb0`). It checks neither `FlashRAM` nor a counter key nor `IsServiceProcess`.

The difference from macOS comes from the A31 registry value `FlashSize = 64,16`. Because its second number is non-zero, `CounterControl` asks `GetCounterAddrSizeFromFlash` (`0x1800eb7f0`, macOS `0x0e7010`) for the area, with address `first × FlashSize[0] × 1024 + second`:

| Source | Key | A31 result | Requests |
|---|---|---|---|
| 0 (flatbed) | `flash_addr_fb_scan` (absent) | `0x00000`, `0x10000` bytes | 16 sector erases, 64-byte write at 0 |
| 1 (positive) | `flash_addr_positive_scan` (absent), then `flash_addr_Postive_IR_Scaling` because `Enable_IR_Scaling[0]` is non-zero | `0x00000`, `0x40` bytes | one 4 KiB sector erase at 0, 64-byte write at 0 |
| 2 (negative) | `flash_addr_negative_scan` (absent) | `0x00000`, `0x10000` bytes | 16 sector erases, 64-byte write at 0 |
| 3 (ADF), counter 0 / 1 | `flash_addr_adf_pad` / `flash_addr_adf_roller` (absent) | `0x10000` / `0x20000` | 16 sector erases there, 64-byte write |
| 4 | `flash_addr_adf_roller` (absent) | `0x20000` | 16 sector erases there, 64-byte write |

Every source from 0 to 2 overwrites the infrared record at address 0. Sources 3 and 4 leave it alone.

### Question 3: serial EEPROM

- `ReadFromNVRAM` (`0x180061130`, macOS `0x061120`) is the same sequence as on macOS (`../protocol/serial-eeprom.md`): `EPROMSEL` on, register `0x8b = 0x30`, busy wait, then per word `0x8b = 0x80 | (address & 0x3f)`, read `0x8f` (low byte), busy wait, read `0x8e` (high byte), busy wait, and at the end `0x8b = 0x00`, busy wait, `EPROMSEL` off. The busy wait `CheckBusy` (`0x180061370`) sleeps 100 ms per round and polls register `0x4f` bit 4 without a limit. `_EPROMSEL` (`0x18006e730`) dispatches on bcdDevice. For `0x0702` it lands in `0x18006e8e0`, which sets bit 3 of the shadow of register `0x0a` and writes it with `WriteRegs`.
- `ReadFromNVRAM` has no caller. `_EPROMSEL` and `CheckBusy` are called only from it.
- The only immediate `0x8b` used as a register number is in `ReadFromNVRAM`. Register `0x8f` appears elsewhere only as the start of a three-register field write (`0x1800344d0`) and in field accessors with base `0x8a` (`0x180068440`, `0x180068770`), which are exposure fields in `CGL126` (`../protocol/serial-eeprom.md`, "Conflict with the exposure registers"). No 93C46 `WRITE`, `ERASE`, `ERAL`, `WRAL` or `EWDS` sequence exists: the engine can only read the EEPROM, and nothing calls that.

### Question 4: USB identity

- No code writes a VID, PID, descriptor or string, and nothing re-enumerates the device: the imports contain no `CM_*` or `SetupDiCallClassInstaller`/`SetupDiChangeState` call, and no `IOCTL_SEND_USB_REQUEST` or `IOCTL_RESET_PIPE` exists. The only USB descriptor access is reading (device descriptor and the serial string, see above).
- USB-core register writes (wValue `0x8c`) use wIndex `0x0f`, `0x10`, `0x13` and `0x17` only (`0x180101150`, `0x180104e60`, `0x1801017c0`), the macOS set without `0x18` (`../protocol/serial-flash.md`, "Where the USB identity comes from"), plus the dataless end-of-transfer request with wIndex 0 for bcdDevice < `0x200` (`0x180100320`, `0x180100ff0`).
- The other `0x8b` writes carry no identity data either: `AHBWriteAddr` (`0x180101820`, wIndex 3) has no caller, `APBWriteData` (`0x1801018a0`, wIndex 5) is used only by an APB read and write test at `0x01100000` (`0x180104d30`, no caller), and the 6-byte write at wIndex `0x0e` (`0x1800fcc90`, `0x1800fcf20`) selects a clock from a table of six values, with USB-core register `0x13` as the alternative path, so it is the AHB clock setting *(inference)*.
- Matching other than VID and PID: none for this model. The HID search for VID `0x0557` PID `0x2405` through `hid.dll` (`0x180103420`) and the EasyPod `ConnectPOD(0x07b3, 0)` (`0x1800266d0`) have no caller.

### Question 5: standby

Same design as macOS (`macos.md`, "Standby"), with two additions.

- `StandbyModeSel` (`0x180061ad0`, macOS `0x061ac0`) clears the `StandbyReg` mask in register `0x31` to enter standby and sets it to leave, with an optional second register and mask pair. `IsStandbyMode` (`0x180061de0`, macOS `0x061d60`), `StandbyModeControl` (`0x180026ef0`, macOS `0x038e50`), `InitStandbyModelOffTimeInfo` (`0x1800268f0`, macOS `0x022ee0`) and `SetStandbyOffTime` (`0x180026a40`, macOS `0x0387a0`) match. The host timer is `(max(StandbyOffTime, 5) − 5) × 60000` ms, 10 minutes for the A31, ticked every 5000 ms through a `CNotify` timer. `StandbyOffTime = 0` keeps the scanner awake. `LoaderReadyReg` (`0x180063fa0`) wakes it when a holder is inserted. `0x180004620` dispatches the timer tick (event `0xff`) to `TestUnitReady` and `SetStandbyOffTime`.
- `Register` pulses standby at open: `StandbyModeSel(1)`, `Sleep(10)`, `StandbyModeSel(0)` (calls at `0x18000667a` and `0x1800066a6`). `StandbyModeControl(0)` is also called from `StartScan` (`0x18000dc10`), `DoCalibration` (`0x180020950`), `0x180027e20`, `0x18002b3b0`, `0x1800e75b0` and the second block of `Register`. `Unregister` (`0x1800075a0`) switches the lamp off with `MyWriteReg` (register 3 twice, then `0x7e`) and calls `StandbyModeControl(1)`.
- New on Windows: in a service process `InitStandbyModelOffTimeInfo` enters standby at once when the timer window (`0x180134070`) does not exist yet. And a hidden window procedure (`0x180084640`) records `WM_POWERBROADCAST` with `PBT_APMSUSPEND` in a flag (`0x18012bc24` bit 0), on which the next `TestUnitReady` calls `StandbyModeControl(1)` before it reinitialises the scanner. `0x180001000` also enters standby after a countdown, but its caller was not found.

### Question 6: other tools and versions

- Among the Plustek binaries in all packages, only `Scanapi.dll` and `Scanapi_x64.dll` import `DeviceIoControl`. `devcon`, `DPInst` and `usbscan.sys` are Microsoft's. The other binaries (`setup.exe`, `isrt.dll`, `Install32/64.exe`, `GetInst32/64.dll`, `IPCSetup.dll`, `Setinf.exe`, `ModifyProfile.exe`, `broadcast.exe`, `AutoSet.dll`) are installer helpers without device access. The engine users are the WIA drivers and `ComScan.exe` listed under "Exports and who calls them". `PkWiaDrv20_A31*.dll` contains the string "Firmware Version" but no firmware update call.
- Engine versions: see "Engine builds in the Windows packages".

### V6.0.0.0 engine

`Scanapi_x64.dll` 1.4.16.0 (2.4 MB, 4489 functions against 2183 in 4.0.0.808) was analysed the same way and rechecked for the points above:

- Strings about flash, firmware, counters, EEPROM, standby, serial number and device identity are unchanged apart from these additions: `flash_addr_sheetfed_300`, `flash_addr_sheetfed_600`, `LoaderEjectStep`, a log line "Register : Serial number is %s on scanner." (`0x180002550`), and a serial-suffixed configuration section `HKEY_LOCAL_MACHINE\%s\VID_%04x&PID_%04x-%s` in the ini loader (`0x1800d1030`, not analysed further). `SupportSerialNumber` is gone.
- `apiUpgradeFirmware` (`0x18003ffe0`) is the same stub. `apiCounterControl` (`0x1800402d0`) still reaches `CounterControl` (`0x1800248b0`) with the same gates, and `GetCounterAddrSizeFromFlash` (`0x180133a30`) resolves the same areas.
- No caller, by the same three checks: `ChipErase` (`0x18016ca60`), `FlashSelfTest` (`0x18016f0a0`), `AsicSelfTest` (`0x18016ecf0`), `WriteAllCountInfo` (`0x180036920`), `WriteIRScalingInfo` (`0x18003c500`) and `ReadFromNVRAM` (`0x180088890`). `BlockErase` (`0x18016cb90`) is called only from `FlashSelfTest`. The other erase and write callers are the V5.0.2.0 set with the same gates.

The three V5.0.x builds before 4.0.0.808 were compared by hash and version only.

## Open questions

1. ~~Which `CGL12x` class and which code paths does the A31 (OpticFilm 120) engine use?~~ bcdDevice `0x0702` selects the slot that is `CGL126` on macOS (`macos.md`, "Which chip class"), and the Windows dispatch uses the same boundaries ("Disassembly", "Device discovery and configuration").
2. ~~Does `apiUpgradeFirmware` apply to the flash?~~ It is a stub in every analysed build (V5.0.2.0, V6.0.0.0, macOS). The flash holds only the infrared record on the owner's unit (`../hardware/flash-dump.md`). Whether it holds firmware or identity on a working unit is still open.
3. If the GL128 boots from external flash, does a blank or corrupted flash explain the Genesys default identity, and does the chip's ROM then accept flash programming over USB? The Windows engine does not answer this: it never reads or writes identity data.
4. Does any third-party application (SilverFast, VueScan) load `Scanapi.dll` and call `apiCounterControl`, which would erase the infrared record?
