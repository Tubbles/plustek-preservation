# Serial flash access (Plustek macOS engine)

How Plustek's macOS scanner engine reaches the serial flash on the scanner board, what it keeps there for the OpticFilm 120 (model code A31, `07b3:1406`), and what the code says about the USB identity. Static analysis only, nothing was executed.

Source: `PLK_A120.framework/Versions/A/ScanApi` from `OpticFilmOF120_V3100_12L.dmg` (engine version 1.4.27.4.0, see `../vendor-driver/macos.md`), x86_64 slice, analysed with Ghidra 12.1.4 (scripts and commands in `../../tools/ghidra/README.md`). Addresses are offsets in the x86_64 slice, which Ghidra loads at image base 0. Every claim names the function it comes from; *(inference)* marks interpretation.

## Transport

Every flash operation is a vendor control transfer built by `CIOUSB::ControlRead` (`0x0f0970`) or `CIOUSB::ControlWrite` (`0x0f0eb0`). Both fill an `IOUSBDevRequestTO` and call `ControlRequestTO` on the interface (vtable slot `0x128`). They report success only when the device transferred exactly wLength bytes.

| Field | Read | Write |
|---|---|---|
| bmRequestType | `0xc0` | `0x40` |
| bRequest | `0xa0` | `0xa0` |
| wValue | `0x008a` | `0x008b` |
| wIndex | selects the operation (table below) | same |

bRequest is the constant `0xa0` in both functions (`movb $0xa0` at `0x0f09b2`), for every request the macOS engine sends. Plustek's Windows driver uses `0x0c` for one-byte transfers and `0x04` for longer ones in the issue #151 capture (`of120-capture-151.md`). Both drivers run the same scanner, so the ASIC apparently does not decode bRequest *(inference)*. A new driver should copy the captured Windows values, which are known to work on an OpticFilm 120.

The engine has two implementations of each flash function. When `CIOUSB::Bcd()` (the device's bcdDevice, stored at `CIOUSB+0x12` by `CIOUSB::DealWithDevice`, `0x0efe40`) equals `0x0602`, it drives a memory-mapped SPI master at bus address `0x03000000` through bulk transfers (`SPI_WriteBusData`, `SPI_ReadBusData`, `SPI_WriteTxData`, `SPI_ReadRxData`). Every other chip, the OpticFilm 120's bcdDevice `0x0702` included, uses the `0x8a`/`0x8b` control requests below. The bus path is described at the end for completeness.

## Requests for bcdDevice other than 0x0602

| Function | Address | Requests sent |
|---|---|---|
| `CIOUSB::SPI_init()` | `0x0f6c00` | write wIndex `0x07`, 1 byte `01`; then write wIndex `0x09`, 4 bytes `00 00 00 00` |
| `CIOUSB::SFlash_RDID()` | `0x0f6dc0` | read wIndex `0x10`, 3 bytes |
| `CIOUSB::SFlash_Read(addr, buf, len)` | `0x0f7d70` | write wIndex `0x0b`, 4 bytes: `addr` as 32-bit little-endian; then read wIndex `0x0f`, 64 bytes, repeated while more than 64 bytes remain, and one last read of the remainder (1 to 64 bytes) |
| `CIOUSB::SFlash_Write(addr, buf, len)` | `0x0f77f0` | write wIndex `0x0b`, 4 bytes `addr` little-endian; then write wIndex `0x0f` with the data in chunks of 64 bytes and a last shorter chunk |
| `CIOUSB::SFlash_SectorErase(addr)` | `0x0f74b0` | write wIndex `0x12`, 3 bytes: `addr` bits 23-16, 15-8, 7-0 (big-endian) |
| `CIOUSB::SFlash_BlockErase(addr)` | `0x0f7410` | write wIndex `0x11`, 3 bytes, `addr` big-endian. This function has no `0x0602` branch: it sends the control request on every chip. |
| `CIOUSB::SFlash_ChipErase()` | `0x0f72c0` | write wIndex `0x10`, no data stage (wLength 0) |
| `CIOUSB::SFlash_Erase(addr, len)` | `0x0f7760` | `SFlash_SectorErase` at `addr`, `addr + 0x1000`, ... until `len` bytes are covered |
| `CIOUSB::SFlash_WREN()`, `SFlash_WRDI()`, `SFlash_ChkWIP()` | `0x0f6fb0`, `0x0f7080`, `0x0f7150` | only the `0x03000000` bus path exists. For other chips they send bulk writes to `0x03000008` and `0x0300000e` that have no meaning there *(inference)*, and nothing in the engine calls them except the `0x0602` branches of `SFlash_Write`, `SFlash_SectorErase` and `SFlash_ChipErase`. |

Notes:

- `SFlash_RDID` stores the three ID bytes in a local buffer and never looks at them (`0x0f6f60` to `0x0f6fa3`): its result is only whether the device answered with 3 bytes. The engine does not check the flash type.
- `SFlash_Read` (`0x0f7d70`) sends the address once per call, then reads 64 bytes per transfer while more than 64 bytes remain, then the rest in one transfer (wLength = rest & `0xff`). Only the host buffer pointer advances between transfers, so the ASIC must advance the flash address by itself *(inference)*. `SFlash_Write` works the same way in the other direction.
- The address field is 32 bits wide: the function's `uint` argument sent as it lies in memory, so little-endian. Neither function checks alignment or an upper bound. The MX25L4005-class part in the capture holds 512 KiB, addresses `0x00000` to `0x7ffff`.
- To an OpticFilm 120 the engine sends flash address 0 and no other (`ReadIRScalingInfo`, and `CounterControl` below for sources 0 to 2). Non-zero addresses go out only on paths this model's plist does not enable (shading and counters of other models) and through `CounterControl` for the ADF sources 3 and 4. So the byte order of a non-zero address is read from the code but unproven on the OpticFilm 120.
- For this path the engine sends no write-enable, no status-register write, no status read and no busy wait around erase and program. Those exist only on the `0x0602` bus path (`SFlash_WREN`, `SFlash_WRDI`, `SFlash_ChkWIP`, last section). The ASIC presumably handles write enable and the busy wait itself *(inference)*.
- Allowlist for any tool that talks to this path: `0x8b` (bmRequestType `0x40`) only with wIndex `0x07`, `0x09` and `0x0b`, and `0x8a` (bmRequestType `0xc0`) only with wIndex `0x10` and `0x0f`. The same two wIndex values are also chip erase (`0x10`) and program (`0x0f`): the read and the destructive write differ only in direction and wValue. Driver code should hard-code each full request (bmRequestType, wValue, wIndex, wLength) and never derive the direction from a variable. wIndex values the binary never uses (table below) are undocumented and may do anything.

### wIndex values of the `0x8a` and `0x8b` requests

Collected from every `ControlRead` and `ControlWrite` call site (`tools/ghidra/ListCallsWithConstants.java`).

| wIndex | Read (`0x8a`) | Write (`0x8b`) | Used by |
|---|---|---|---|
| `0x0000` | 1 byte, GPIO input byte (mask from plist `ButtonIORead`) | | `CIOUSB::ReadButtonID` `0x0f21b0` (bcdDevice ≥ `0x600`), after a write of `00` with wValue `0x89` |
| `0x0003` | | 4 bytes, AHB address, little-endian | `CIOUSB::AHBWriteAddr` `0x0f66e0`. No caller in the binary. |
| `0x0004` | | 1 byte `00` | `CIOUSB::HardwareResetScanner` `0x0f8370`. No caller in the binary. |
| `0x0005` | 4 bytes, APB data | 4 bytes, APB data | `CIOUSB::APBReadData` `0x0f6830` (called from `ReadBulkData` and `CScan::DoScanThread`), `CIOUSB::APBWriteData` `0x0f67c0` (no caller in the binary) |
| `0x0006` | | 4 bytes, APB address, little-endian | `CIOUSB::APBWriteAddr` `0x0f6750` |
| `0x0007` | | 1 byte `01` | `CIOUSB::SPI_init` |
| `0x0009` | | 4 bytes `00 00 00 00` | `CIOUSB::SPI_init` |
| `0x000b` | | 4 bytes, flash address, little-endian | `SFlash_Read`, `SFlash_Write` |
| `0x000a` | register read, wIndex `(register << 8) \| 0x0a` | 2 bytes: register, value | second entry of the request tables in `ReadReg`, `ReadRegs` and `WriteReg` (`0x0f2c50`), never selected (see below) |
| `0x000e` | | 6 bytes `10 00 00 02 v v` or `2b 00 00 02 v v` | `CIOUSB::SysClock` `0x0f0a20` and `CIOUSB::AhbClock` `0x0f0fa0` when their second argument is true. Their only callers, `CAsic::SetSystemClock` (call at `0x05a5cf`) and `CAsic::SetAHBClock` (call at `0x05a8d6`), pass false, so this is not sent. The other `SysClock` calls (`CAsic::PixelTime`, `CAsic::MotorUnitTime`) go to the overload without arguments at `0x058d10`, a getter. |
| `0x000f` | flash data, up to 64 bytes | flash data, up to 64 bytes | `SFlash_Read`, `SFlash_Write` |
| `0x0010` | 3 bytes, JEDEC ID | no data: chip erase | `SFlash_RDID`, `SFlash_ChipErase` |
| `0x0011` | | 3 bytes, address big-endian: block erase | `SFlash_BlockErase` |
| `0x0012` | | 3 bytes, address big-endian: sector erase | `SFlash_SectorErase` |
| `0x26fe` | 1 byte | 1 byte `00`, only if bit 0 of the byte read was set | `CIOUSB::InitInterrupt` `0x0f86a0` |

`CIOUSB::ReadReg` (`0x0f2670`), `CIOUSB::ReadRegs` (`0x0f29a0`) and `CIOUSB::WriteReg` (`0x0f2c50`) also hold a second encoding (wValue `0x8a` or `0x8b` with wIndex `(register << 8) | 0x0a` for reads, wIndex `0x0a` for writes) in a two-entry table, but always pick the first entry (wValue `0x8e`/`0x83`). The second encoding is never sent.

The small wIndex values look like command numbers and `0x26fe` like an address in the ASIC's internal address space *(inference from the values only)*.

### The five requests of the issue #151 capture

| Capture (`of120-capture-151.md`, set C) | Function | Meaning |
|---|---|---|
| C1 `40 0c 008b` wIndex 7, data `01` | `SPI_init`, first request | enable or select the SPI interface *(inference from the name)* |
| C2 `40 04 008b` wIndex 9, data `00 00 00 00` | `SPI_init`, second request | SPI set-up, purpose of the zeros unknown |
| C3 `c0 04 008a` wIndex `0x10`, 3 bytes → `c2 20 13` | `SFlash_RDID` | JEDEC ID read. Macronix MX25L4005 class (`of120-capture-151.md`). |
| C4 `40 04 008b` wIndex `0x0b`, data `00 00 00 00` | `SFlash_Read(0, buf, 0x40)`, address set-up | flash address 0 |
| C5 `c0 04 008a` wIndex `0x0f`, 64 bytes | `SFlash_Read`, data read | 64 bytes from flash address 0, the infrared scaling record below |

The `SFlash_Read(0, buf, 0x40)` call comes from `CScanApi::ReadIRScalingInfo` (`0x03ae60`).

## When the engine touches the flash at open

`CScanApi::Register` (`0x01da80`) opens the scanner. With bcdDevice ≥ `0x400` and plist key `FlashRAM` non-zero (the OpticFilm 120 plist has `FlashRAM = 1`) it calls `SPI_init`, then `SFlash_RDID` (calls at `0x01e1b0` and `0x01e1ca`), and only if RDID succeeded, `GetAllCounterInfo` (when a counter key is set, see below) and `ReadIRScalingInfo` (when the first value of `Enable_IR_Scaling` is non-zero, once per process). Later, after taking its scanner lock again, it sends `SFlash_RDID` once more (`0x01efb9`), with `SPI_init` (`0x01ef98`) only when the "SPI initialised" flag at `CScanApi+0x2e` is clear, which the earlier calls have set. `CScanApi::SoftwareResetScanner` (`0x0338a0`), which `Register` calls first, already sends `SPI_init` and `SFlash_RDID` (`0x033be7`, `0x033bfe`). So the macOS engine sends `SPI_init` twice, RDID three times and the 64-byte read once at open. The Windows capture shows each once (Windows driver version differs).

Plist keys (registry values) default to 0 when absent: `CRegistry::ReadKey(NULL)` (`0x08b090`) clears the whole value table before parsing.

## What the engine keeps in flash for the OpticFilm 120

### Infrared scaling record: address 0, 64 bytes

`CScan::GetCounterAddrSizeFromFlash(addr, size, 1, 0)` (`0x0e7010`) resolves the record from plist key `flash_addr_Postive_IR_Scaling = 0,0x00000,0x00040` (in `Add-On`) as `addr = first × FlashSize × 1024 + second`, `size = third`. The OpticFilm 120 plist has no `FlashSize` key, so FlashSize is 0 and the first value 0 anyway: address `0x00000`, size `0x40`.

`ReadIRScalingInfo` (`0x03ae60`) reads 64 bytes there and takes seven 32-bit little-endian words: word 0 as an integer, words 1 to 6 converted to floating point, stored in the `CScan` object (offsets `0x880`, `0x828`, `0x830`, `0x858`, `0x838`, `0x840`, `0x860`). The working unit in the capture returned 5300, 541, 10495, 580, 586, 10461, 600 and `0xff` fill, which fits this layout.

`CScanApi::WriteIRScalingInfo` (`0x0484f0`) can write the record (erase 4 KiB at the address, then write 64 bytes taken from plist `Enable_IR_Scaling`), but nothing in the binary calls it. The record was presumably written at the factory *(inference)*.

### Shading data: not in flash on this model

`CScan::WhiteShading` (`0x0af330`), `CScan::SetShadingData` (`0x094a30`), `CScan::FlatbedShading` (`0x0def90`) and `CScanApi::GetShadingInfo` (`0x0455e0`) use the flash for shading only when bcdDevice ≥ `0x600`, `FlashRAM` is set and plist key `SaveShadingToFlash` is non-zero. The OpticFilm 120 plist has no `SaveShadingToFlash`, so its shading goes to host files (`SaveShadingFile`). `CScan::WriteShadingDataToFlash` (`0x0d5740`) also needs key `ShadingFile`. `CScan::EraseShadingDataOnFlash` (`0x0e0cf0`) erases fixed ranges (`0x30000` and `0x70000`, `0x40000` bytes each, when `FlashSize` is 0) but is only called from the CIS and sheet-fed calibration paths.

### Usage counters

`CScanApi::GetAllCounterInfo` (`0x039500`), `CScanApi::WriteScanningCountInfo` (`0x0427f0`) and `CScanApi::WriteAllCountInfo` (`0x045ef0`) keep scan counters as cleared bits in 64 KiB flash areas (default areas `0x00000` for flatbed, positive and negative, `0x10000` and `0x20000` for ADF pad and roller, per `GetCounterAddrSizeFromFlash`). They touch the flash only when a per-counter flag is set (`_CounterInfo` bit 0 and the flags at `0x10b830` to `0x10b860`). `GetAllCounterInfo` and `CScanApi::GetDeviceCapability` (`0x01fe40`) set those flags only when `FlashRAM` is non-zero and the matching plist key is set (`RftCounterScan`, `PosCounterScan`, `NegCounterScan`, `AdfCounterPad`, `AdfCounterRoller`, `ShtCounterScan`). The OpticFilm 120 plist sets none of these keys, so these three functions never read or write a counter. `WriteScanningCountInfo` still sends `SPI_init` when the SPI was not initialised yet.

`CScanApi::CounterControl` (`0x0354e0`) is the exception. It is reached from the exported `apiCounterControl` (`0x035450`, also in the table `_SCANAPI_GetFunctionTable` returns, `0x037690`), with a source and a three-field control block (action, counter, value). Actions 0 and 1 only return counts held in memory. Action 2 with counter 0 rewrites the source's counter area: it moves the running count into the total, fills a 64 KiB buffer with `0xff`, puts 0 in word 0 and the total in word 1, then calls `SFlash_Erase(addr, 0x10000)` and, if that succeeded, `SFlash_Write(addr, buffer, 64)` (64 bytes on every chip but `0x0602`). `addr` is `0x00000` for sources 0, 1 and 2 (flatbed, positive, negative), `0x10000` or `0x20000` for source 3 (counter 0 or 1) and `0x20000` for source 4, unless plist `FlashSize` is non-zero, which it is not for the OpticFilm 120. Its only gates are an open session, `TestUnitReady` and the scanner lock. It does not check `FlashRAM`, the counter keys or the counter flags.

On an OpticFilm 120, one `apiCounterControl` call with action 2 and source 0, 1 or 2 would send 16 sector erases (`0x8b` wIndex `0x12`, addresses `0x00000` to `0x0f000`), wiping the infrared record and the whole first 64 KiB, then write 64 bytes at address 0. Address 0 would then read `00 00 00 00`, the total as LE32 (0 when no counter was ever loaded *(inference)*), and `0xff` for the rest. Whether SilverFast or VueScan ever call `apiCounterControl` was not checked.

### Serial number: not read from flash

`CScan::GetSerialNumberInfo` (`0x0e7490`) and `CScan::SetSerialNumberInfo` (`0x0e74d0`) only log their name and return 0. `apiGetDeviceSerialNumber` (`0x035150`) returns the global `g_pbSerialNumber`, which nothing in the binary sets (`CScanApi::Unregister`, `0x01f470`, only clears it). The only serial number the engine uses is the USB serial number string (IOKit property `USB Serial Number`, read in `CIOUSB::DealWithDevice`), which selects the configuration file (see `../vendor-driver/macos.md`). The OpticFilm 120 has no serial number string (iSerialNumber 0).

### Other non-volatile storage code

`CAsic::ReadFromNVRAM` (`0x061120`) reads a Microwire-style serial EEPROM through ASIC registers: it sets `EPROMSEL`, writes `0x30` to register `0x8b`, then for each 16-bit word writes `0x80 | address` to register `0x8b` and reads the low and high byte from registers `0x8f` and `0x8e`. Nothing in the binary calls it, and `CIOUSB::FlashSelfTest` (`0x0f8410`) only returns 1 without any USB traffic.

### Flash layout implied for the OpticFilm 120

| Range | Content | Source |
|---|---|---|
| `0x00000` to `0x0003f` | infrared scaling record, seven 32-bit words, rest `0xff` | `ReadIRScalingInfo`, plist, capture |
| `0x00000` to `0x0ffff` | erased and overwritten by `CounterControl` action 2 for sources 0 to 2 (see "Usage counters") | `CounterControl` |
| `0x10000` to `0x2ffff` | erased and overwritten by `CounterControl` action 2 for the ADF sources 3 and 4 | `CounterControl` |
| everything else up to `0x7ffff` | not referenced by the engine for this model | |

Apart from the infrared record, the engine reads nothing from the part on this model. The only flash writes reachable on this model are the `CounterControl` path above (`WriteIRScalingInfo` has no caller).

## `apiUpgradeFirmware`

`apiUpgradeFirmware(void*, unsigned int, unsigned int, bool)` (`0x0350e0`) is a stub in this build: it logs its name and returns `0xffffffa2` (−94) when no scanner session is open, `0xffffffa0` (−96) otherwise. It sends no USB request, touches no flash, reads no file and uses none of its arguments. There is no firmware image in the binary: no caller passes one, and the byte search below finds no descriptor-shaped data. Which code Plustek's Windows engine has behind its `apiUpgradeFirmware` export was not analysed.

## Where the USB identity comes from

What the macOS engine shows:

1. Device matching uses VID and PID only. `CIOUSB::FindDevice` (`0x0f05b0`) asks IOKit for `IOUSBDevice` services with `idVendor` = `VendorID` and `idProduct` = `ProudctID` (sic) from `Prereference.plist` (1971 = `0x07b3`, 5126 = `0x1406`). `CIOUSB::DealWithDevice` checks the same values again, then only records bcdDevice and the serial number string. Strings and string indices play no part. A unit reporting `05e3:0103` is never opened.
2. No code writes a VID, PID, string or descriptor anywhere. `0x07b3` appears as an instruction operand once (a comparison in `CIOUSB::ClosePipes`), `0x1406` and `0x1440` only in comparisons (`CIOUSB::Interrupt`, `CScan::DeleteShadingFiles`), `0x05e3` and `0x0103` never (`tools/ghidra/FindScalars.java`). `tools/ghidra/find_descriptor_bytes.py` finds no device descriptor header, no little-endian VID/PID pair and no "Film Scanner", "USB2.0 Scanner" or "Genesys" text in ASCII or UTF-16LE in either slice. The Windows `Scanapi_x64.dll` and `Scanapi.dll` contain "Film Scanner" only inside registry paths (`Software\Film Scanner\A28\VxD`).
3. The only writes to USB-core registers (request `0x8c`, `CIOUSB::WriteUsbReg`, `0x0f0f60`, and direct calls) use wIndex `0x0f` (bulk delay or mode), `0x10` (system clock), `0x13` (AHB clock), `0x17` (ADF interrupt, other models) and `0x18` (DMA status). None of them carries identity data.
4. AHB and APB access: `AHBWriteAddr` has no caller. APB reads are used for a scan counter at `0x01100000` during automatic ADF scans (`CScan::DoScanThread`, `0x0c2a00`) and for 16-bit reads in `0x01000000` to `0x01000a80` inside `CIOUSB::ReadBulkData` (`0x0f5c20`). No APB write path carries identity data.
5. The flash is read only at address 0 for 64 bytes on this model, and its content (seven numbers) has no relation to the identity.
6. The only re-enumeration in the engine is in `CIOUSB::ClosePipes` (`0x0f13e0`): for `07b3:131c` with bcdDevice ≥ `0x600` it calls IOKit's `USBDeviceReEnumerate` and `ResetDevice` on close. Nothing similar exists for the OpticFilm 120.

Conclusion from the code: the host software never reads, writes or supplies the USB identity. The identity therefore comes from the scanner itself, without the host: either from the ASIC's built-in defaults, or from configuration the ASIC loads at power-on before it enumerates. The serial flash is the obvious candidate for that configuration, since the engine uses less than 0.02 % of it *(inference)*. That the owner's unit falls back to Genesys defaults with different string indices fits "configuration not loaded, ROM defaults used" *(inference)*. What remains unknown: whether the GL128 loads anything from the flash at power-on at all, at which offset and in which format, and whether the owner's flash is blank, damaged or unreadable. A full flash dump from the owner's unit, and ideally one from a working unit for comparison, would settle it.

The owner's dump (`../hardware/flash-dump.md`) holds the infrared record and nothing else, so on that unit the flash carries no identity. A dump of a working unit is still missing. The other candidate is a serial EEPROM on the ASIC's own EEPROM interface (`EPROMSEL`, read by the uncalled `CAsic::ReadFromNVRAM`, "Other non-volatile storage code" above).

## Reading the whole flash over USB

The engine's own `SFlash_Read` accepts any 32-bit address and any length, so the whole 512 KiB can be read with the same two requests the vendor driver sends at every open:

1. `SPI_init`: `40 xx 008b` wIndex `0x07` data `01`, then `40 xx 008b` wIndex `0x09` data `00 00 00 00`.
2. Optionally `SFlash_RDID`: `c0 xx 008a` wIndex `0x10`, 3 bytes.
3. For each 64-byte block: `40 xx 008b` wIndex `0x0b` with the 4-byte little-endian address, then `c0 xx 008a` wIndex `0x0f`, 64 bytes. Sending the address before every block avoids relying on the auto-increment that `SFlash_Read` relies on for longer reads. 8192 blocks cover `0x00000` to `0x7ffff`.

`xx` is bRequest: `0x0c` for one-byte and `0x04` for longer transfers as in the Windows capture, or `0xa0` as the macOS engine sends.

Caveats:

- The captured traffic shows only address 0. The wIndex `0x0b` request with a non-zero address has not been seen on the wire, though the macOS code sends it for shading and counters on other models. Its byte order is read from the code, not confirmed on an OpticFilm 120 (see the notes under "Requests for bcdDevice other than 0x0602").
- Both vendor drivers send the SPI init and address requests only after the register blast and the clock set-up (`of120-capture-151.md`, steps 2 to 5 of the open; `SoftwareResetScanner` in the macOS engine). Without that set-up the requests may fail or return wrong data. Per the host code that is not destructive, but it has not been tried on hardware. On the owner's unit, whether the ASIC runs these requests at all in its current state is unknown.
- Keep wLength at 64 or less for wIndex `0x0f`. The engine never asks for more.
- Send only the requests of the allowlist above.

`tools/pi/flash_dump.py` implements this dump. It refuses any OUT request outside the allowlist, checks that a non-zero address is applied as sent before the full dump, reads the image twice (the second pass in descending address order) and checks the result for address aliasing. Its docstring has the details and exit codes.

## Requests that could restore the identity

None that sends identity data. The only non-volatile write paths are `SFlash_Write` (wIndex `0x0f` after `0x0b`) and the erase requests (wIndex `0x10`, `0x11`, `0x12`). If the identity turns out to live in the flash, those requests could write it back, but the engine contains no image or record to write: restoring would need the content from a working unit's flash, or knowledge of the format. `HardwareResetScanner` (wIndex `0x04`) has no caller, and what it resets is unknown.

## The SPI master at 0x03000000 (bcdDevice 0x0602 only)

For reference, the other chip's path, read from the same functions. Registers are 16 bits wide and accessed with `SetupBulkLength` plus bulk transfers (`../protocol/usb-requests.md`).

| Address | Use |
|---|---|
| `0x03000000`, `0x03000002` | configuration, written `4` and `1` by `SPI_init` |
| `0x03000004` | start: `0x10` receive, `0x20` transmit, `0x810` read, `0x820` program |
| `0x03000006` | status: bit 1 transmit done, bit 0 receive done, write 1 to clear |
| `0x03000008` | command descriptor (opcode and length) |
| `0x0300000a`, `0x0300000c` | further command bytes (RDID writes `0x9f9f` to both) |
| `0x0300000e` | data FIFO |

Opcodes used: `0x9f` read ID, `0x06` write enable, `0x04` write disable, `0x05` read status (busy bit 0), `0xd8` block erase (in `SFlash_SectorErase`'s bus branch), `0xc7` chip erase.
