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

## What `Scanapi.dll` contains (strings only, not yet disassembled)

- One codebase for several Genesys chips: C++ classes `CGL125`, `CGL126`, `CGL128`, `CGL846` (RTTI names). Plustek's folder name calls the OpticFilm 120 engine "GL126" while SANE's chip probe says GL128 for bcdDevice `0x0702`. Which class the OpticFilm 120 uses is not known yet.
- Device lookup by VID/PID: `HKEY_LOCAL_MACHINE\%s\VID_%04x&PID_%04x`, `ScanApi_%04x_%04x.ini`. Together with `scannerid` this points to the engine opening only `07b3:1406`, in which case editing the INF alone would not make a `05e3:0103` unit usable. To be confirmed by disassembly.
- Firmware and flash handling: `apiUpgradeFirmware`, `apiGetDeviceSerialNumber`, `CheckFlashRam`, `FlashRAM`, `FlashSize`, "Are you sure to erase flash address from 0x%08x to 0x%08x ?", "Are you sure to test read/write flash ?", "Chip/Sector Erase start/finished", "Flash data compare OK !", `SaveShadingToFlash`, and a family of `flash_addr_*` names (`flash_addr_negative_scan`, `flash_addr_positive_scan`, `flash_addr_Postive_IR_Scaling`, many ADF and flatbed ones). Some of these clearly belong to document scanners sharing the codebase (ADF, duplex, seven segment display), so their presence says nothing yet about the OpticFilm 120 board.
- Host side files: `filmholderposition.dat`, `autoposition.dat`, `Global\%d%dserialnumber.dat`.
- "Register : read data from f/w -- Reg = 0x%04x ..." and "waiting data ready interrupt from f/w": some models run firmware that the engine talks to through registers and the interrupt endpoint.

## Open questions

1. Which `CGL12x` class and which code paths does the A31 (OpticFilm 120) engine use?
2. Does the OpticFilm 120 board have a flash chip holding firmware, configuration (USB identity) or calibration data, and does `apiUpgradeFirmware` apply to it?
3. If the GL128 boots from external flash, does a blank or corrupted flash explain the Genesys default identity, and does the chip's ROM then accept flash programming over USB?
