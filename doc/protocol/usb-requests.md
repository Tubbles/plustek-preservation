# USB request encoding (Plustek macOS engine)

The encoding of every `CIOUSB` primitive in Plustek's macOS engine (`PLK_A120.framework/Versions/A/ScanApi`, version 1.4.27.4.0), x86_64 slice, read with Ghidra (`../../tools/ghidra/README.md`). Addresses are offsets in that slice. The serial flash requests are in `serial-flash.md`; this file covers the rest. *(inference)* marks interpretation. Nothing was executed.

Request notation follows `of120-capture-151.md`: `bmRequestType bRequest wValue`, then wIndex, wLength and data.

## Common rules

- All vendor requests go through `CIOUSB::ControlRead` (`0x0f0970`, bmRequestType `0xc0`) or `CIOUSB::ControlWrite` (`0x0f0eb0`, `0x40`), except `CIOUSB::MyWriteReg` which builds its own request. Arguments are (wValue, wLength, buffer, wIndex). Success means the transfer completed with exactly wLength bytes.
- **bRequest is always `0xa0`** in the macOS engine. Plustek's Windows driver (issue #151 capture) sends `0x0c` for one-byte and `0x04` for longer transfers with the same wValue, wIndex and data. The ASIC apparently ignores bRequest *(inference: both drivers run the same scanner)*. Below, requests are written with `xx` for bRequest.
- Most requests are wrapped in `CIOUSB::Lock_U` (`0x0f0da0`), a host-side lock with no USB traffic.
- Chip generation is chosen by bcdDevice (`CIOUSB::Bcd()`, see "Identity getters"). The OpticFilm 120 reports `0x0702`; branches for other values are mentioned only where they explain a request.
- The macOS engine never sends the one-byte read at wIndex `0x20` (the "link check" returning `0x55`) that the Windows driver sends after nearly every write. Every `0x8e` read it sends is listed in this file.

## Registers

| Function | Address | Request | Data |
|---|---|---|---|
| `ReadReg(reg, uchar*)` | `0x0f2670` | `c0 xx 008e` (`018e` when `reg & 0x100`), wIndex `(reg & 0xff) << 8 | 0x22`, wLength 2 | answer `value 55`; fails unless the second byte is `0x55` |
| `ReadReg(reg, ushort*)` | `0x0f27b0` | same wValue and wIndex, wLength 3 | answer `a b 55`; result `a << 8 | b` *(the ASIC returning consecutive registers is inferred from the code, not seen in the capture)* |
| `ReadReg(reg, uint*)` | `0x0f2890` | same, wLength 5 | answer `a b c d 55`; result big-endian `a b c d` |
| `ReadRegs(reg, buf, count)` | `0x0f29a0` | one 2-byte `ReadReg` request per register, `reg`, `reg + 1`, ... | |
| `ReadRegBit(reg, bit)` | `0x0f65e0` | one 2-byte read | returns `(value >> bit) & 1` |
| `WriteReg(reg, uchar)` | `0x0f2c50` | `40 xx 0083` (`0183` when `reg & 0x100`), wIndex 0, wLength 2 | `reg & 0xff, value`. Also updates the host's register shadow (`CIOUSB+0xe0`). |
| `WriteReg(reg, ushort)` | `0x0f2db0` | through `WriteRegs` | pairs `(reg, value >> 8)`, `(reg + 1, value & 0xff)` |
| `WriteReg(reg, uint)` | `0x0f3550` | through `WriteRegs` | pairs `(reg, bits 23-16)`, `(reg + 1, bits 15-8)`, `(reg + 2, bits 7-0)` |
| `WriteRegs(reg, values, count, ...)` | `0x0f2eb0` | `40 xx 0083`, wIndex 0, up to 64 bytes per transfer; registers with bit `0x100` set go in separate `40 xx 0183` transfers | address and value byte pairs, at most 32 pairs per transfer. With `reg = 0xffff` the buffer already holds pairs, otherwise consecutive registers starting at `reg`. |
| `WriteRegBit(reg, shift, width, value)` | `0x0f6490` | `ReadReg` then `WriteReg` | read-modify-write of `width` bits at `shift` |
| `WriteAllReg()` | `0x0f3650` | `WriteRegs` in pair mode | every register the host marked changed in its shadow (`CRegister::GetAddrData`), then clears the marks. This produces the "register blast" of the capture. |
| `MyWriteReg(reg, value)` | `0x0f2ba0` | `40 a0 0083`, wIndex 0, wLength 2 | the two bytes of `reg` as a 16-bit little-endian number. `value` is never sent (`0x0f2bc0` to `0x0f2c06`), so the ASIC gets register `reg & 0xff` = `reg >> 8`, which is 0 for every call in the binary. No shadow update, no wLength check. Called by `CScanApi::Unregister` (`0x01f470`: register 3 twice, register `0x7e`), `CScanApi::Oldapi` and `CScanApi::Register` (lamp warm-up, not for the OpticFilm 120, whose `LampType` is 1). |
| `SetRegAddr(reg)` | `0x04c500` | `40 xx 0083`, wIndex 0, wLength 1 | `reg`. Used only for bcdDevice < `0x600`. |

The capture confirms this framing for the OpticFilm 120: `40 04 0083` with up to 32 pairs, `40 04 0183` for `0x114` and `0x115`, `c0 04 008e` and `c0 04 018e` with wIndex `0xNN22`.

## Front end (AFE)

For bcdDevice ≥ `0x606` the AFE goes through ASIC registers named in plist keys `AfeWriteReg` (`0x51,0x5d,0x5e` for the OpticFilm 120) and `AfeReadReg` (`0x50,0x107,0x108`). Older chips use fixed registers `0x51`, `0x3a`, `0x3b`.

| Function | Address | Requests |
|---|---|---|
| `WriteAfe(index, value)` | `0x0f3950` | one `WriteRegs` transfer of three pairs: `(0x51, index)`, `(0x5d, value >> 8)`, `(0x5e, value & 0xff)` |
| `ReadAfe(index, *value)` | `0x0f3b50` | `WriteReg(0x50, index)`, `ReadReg(0x107)`, `ReadReg(0x108)`; result `(r107 & 1) << 7 | (r108 & 0x7f)`. For bcdDevice `0x600` to `0x605` the reads are registers `0x46` and `0x47`. |
| `WriteAllAfe()` | `0x0f3dd0` | one three-pair `WriteRegs` transfer per AFE register marked changed |

## USB-core registers (wValue 0x8c)

| Function | Address | Request |
|---|---|---|
| `WriteUsbReg(index, value)` | `0x0f0f60` | `40 xx 008c`, wIndex `index`, 1 byte `value` |
| `SysClock(MHz, false)` | `0x0f0a20` | bcdDevice ≥ `0x600`: `WriteUsbReg(0x10, v)` with v = `0x0a` (24 MHz), `0x0b` (30), `0x0c` (40), `0x0d` (48), `0x0e` (60). bcdDevice `0x300` to `0x5ff`: v = `0x84` (12), `0x94` (24), `0xa4` (30), `0xd4` (40), `0xb4` (48), `0xc4` (60). |
| `AhbClock(MHz, false)` | `0x0f0fa0` | bcdDevice ≥ `0x600` only: `WriteUsbReg(0x13, v)`, same table plus `0x0f` (80 MHz) |
| `SetBulkDelay(n)` | `0x0f5e60` | `40 xx 008c`, wIndex `0x0f`, 1 byte (default 2) |
| `SetBulkMode(...)` | `0x0f4040` | bcdDevice < `0x600`: `WriteUsbReg(0x0f, ...)` and a `0x82` header |
| `EnableAdfInterrupt()` | `0x0f6640` | `40 xx 008c`, wIndex `0x17`, 2 bytes `8a 0a` |
| `FFCFG_chk_DMA_Stop()` | `0x0f6080` | `c0 xx 008e` wIndex `0x18`, 1 byte; if bits `0x0c` are set, write it back with those bits cleared (`40 xx 008c` wIndex `0x18`), read again, then `CancelBulk` |
| `FFCFG_chk_DMA_finish()` | `0x0f5b60` | polls `c0 xx 008e` wIndex `0x18` every 20 ms until bits `0x0c` are clear |

`CAsic::SetSystemClock` (`0x05a4d0`) and `CAsic::SetAHBClock` (`0x05a870`) both pass the plist's `SystemClock` (48 for the OpticFilm 120), so the open sends `0x8c` index `0x10` = `0x0d` and index `0x13` = `0x0d`, as in the capture. The plist key `AHBClock` (60) is not read by this engine: no accessor for it exists. With the second argument true, `SysClock` and `AhbClock` would send `40 xx 008b` wIndex `0x0e` with 6 bytes instead; no caller does.

## Bulk transfers

| Function | Address | Requests |
|---|---|---|
| `SetupBulkLength(addr, len, mode)` | `0x0f4350` | `40 xx 0082`, wIndex `mode`, 8 bytes: `addr` and `len` as 32-bit little-endian. `mode` 0 = read, 1 = write, 8 = read the whole scan in one stream. If plist key `BULK1024` is set, `FFCFG_chk_DMA_Stop` runs first. |
| `BulkRead(buf, len)` | `0x0f1660` | `ReadPipeTO` on the bulk IN pipe with a 3 s timeout, in whole packets. A partial last packet is read in full; the surplus is kept for the next call. |
| `BulkWrite(buf, len)` | `0x0f1980` | `WritePipeTO` on the bulk OUT pipe |
| `ReadBulkData(addr, buf, len)` | `0x0f5c20` | `SetupBulkLength(addr, len, 0)` then `BulkRead`. Exception: for `0x01000000 ≤ addr < 0x01000a80` without `BULK1024`, one APB access per 16-bit word (`APBWriteAddr(addr + 2i)`, `APBReadData`). |
| `WriteBulkData(addr, buf, len)` | `0x0f5ad0` | `SetupBulkLength(addr, len, 1)` then `BulkWrite` |
| `StartReadTransaction(len, addr)` | `0x0f4260` | bcdDevice ≥ `0x600`: `SetupBulkLength(addr, len, 0)` |
| `StartWriteTransaction(len, addr)` | `0x0f4450` | bcdDevice ≥ `0x600`: `SetupBulkLength(addr, len, 1)` |
| `ReadRawData`, `WriteRawData` | `0x0f4830`, `0x0f4990` | `BulkRead` or `BulkWrite`, limited to the bytes left in the current transaction (`CIOUSB+0x54`) |
| `EndReadTransaction()`, `EndWriteTransaction()` | `0x0f5600`, `0x0f45a0` | bcdDevice ≥ `0x200`: if bytes of the transaction were left unread or unwritten, `40 xx 008d` wIndex 0, 1 byte `00`; then poll `c0 xx 008e` wIndex `0x18`, 1 byte, up to 256 times until bits `0x0c` are clear. bcdDevice < `0x200`: `40 xx 008c` with no data, only when bytes were left. |
| `ReadTransaction`, `WriteTransaction` | `0x0f54d0`, `0x0f5840` | Start, raw transfer, End, repeated until the length is done |
| `ReadData(addr, buf, len)` | `0x0f5990` | bcdDevice ≥ `0x600`: `ReadTransaction` at `addr` |
| `WriteData(addr, buf, len)` | `0x0f4b20` | bcdDevice ≥ `0x600` without `BULK1024`: `WriteTransaction` at `addr`. With `BULK1024`: 4 KiB chunks, each written, read back and compared, up to 20 tries, `CancelBulk` on mismatch. |
| `WriteSramData(addr, buf, len)` | `0x0f5330` | bcdDevice ≥ `0x600`: `SetupBulkLength(addr, len, 1)` then `WriteRawData` (no End step) |
| `CancelBulk()` | `0x041e40` | `40 xx 008d`, wIndex 0, 1 byte `00` |
| `SetDataBulk`, `SetRegBulk` | `0x0f5f50`, `0x0f6240` | older `0x82` header layouts for bcdDevice < `0x600` |

So the `0x8d` write after each image in the capture (frames 7143 and 15307) is `EndReadTransaction` closing a read transaction that still had bytes outstanding, or `CancelBulk` *(inference: the macOS engine sends it in both cases, the capture cannot tell which)*. The one-byte read at wIndex `0x18` that returns `0x02` after every buffer transfer in the capture is the busy poll that follows: bits `0x0c` clear means done.

`CScan::StartScanThread` (`0x0c8250`) uses mode 8 (one header for the whole scan) only when the scan has no line limit (`GetLimitScan()` returns 0). The OpticFilm 120's speed blocks set `LimitScan = 0x80000`, so it reads in chunks with mode 0, as in the capture.

`CAsic::CleanUserData(n)` (`0x05b150`) is called by `CScanApi::Register` with n = 0 and n = 1 (`0x01e6c1`, `0x01e6dc`) and writes 34 bytes with `WriteData` to `UserAddr(n)`. For `CGL126` (`CGL126::UserAddr`, `0x080b30`) that is `0xfff00 + n` when `DRAMSEL` is 4 and `DPIHW` is 1 to 3; the OpticFilm 120 base table has `DRAMSEL` 4 (`0x0b = 0x6c`) and `DPIHW` 3 (`0x05 = 0xc8`). The function clears 36 bytes starting 4 bytes before its source buffer (`memset` of `0x24` bytes at `this+0x8040`, source `this+0x8044`, length `0x22`), so the first 32 bytes sent are zero and the last 2 are whatever the buffer held. It returns without sending anything when plist key `DisableUserData` is 1, which the OpticFilm 120 plist sets. This plausibly explains the two unexplained 34-byte writes to `0x000FFF00` and `0x000FFF01` that pyopticfilm replays from the 8200i SE's Windows driver (`pyopticfilm/src/pyopticfilm/asic/gl128.py`, lines 154 to 160): addresses and length match, and so does the content: the first blob is 34 zero bytes and the second is 32 zero bytes followed by `33 00`, which fits the two bytes the `memset` leaves uncleared *(inference: what those two bytes hold at that point was not traced)*.

## AHB and APB

| Function | Address | Request |
|---|---|---|
| `AHBWriteAddr(addr)` | `0x0f66e0` | `40 xx 008b`, wIndex 3, 4 bytes little-endian. No caller. |
| `APBWriteAddr(addr)` | `0x0f6750` | `40 xx 008b`, wIndex 6, 4 bytes little-endian |
| `APBWriteData(value)` | `0x0f67c0` | `40 xx 008b`, wIndex 5, 4 bytes. No caller. |
| `APBReadData(*value)` | `0x0f6830` | `c0 xx 008a`, wIndex 5, 4 bytes |

The only APB users are `ReadBulkData` (above) and `CScan::DoScanThread` (`0x0c2a00`), which reads `0x01100000` during automatic ADF scans.

## Interrupt and buttons

| Function | Address | Behaviour |
|---|---|---|
| `InitInterrupt()` | `0x0f86a0` | `c0 xx 008a` wIndex `0x26fe`, 1 byte. If bit 0 is set, `40 xx 008b` wIndex `0x26fe` with `00`. Opens nothing; called first in `CScanApi::Register` (`0x01dc18`). In the capture the answer was `0x00`, so no write followed. *(inference: clears a latched event flag)* |
| `Interrupt(*value)` | `0x0f1f60` | bcdDevice ≥ `0x400` (or `0x302`, `0x306`): `c0 xx 008e` wIndex `0x21`, 1 byte. |
| `Interrupt(*value, delay, bool, force)` | `0x0f2010` | When the PID is `0x1406` or `0x1440`, or `force` is set, and bcdDevice ≥ `0x400`: the same wIndex `0x21` read, then 10 ms sleep. Otherwise a synchronous 1-byte read of the interrupt pipe (`ReadInterrupt(buf, 0)`). A non-zero result is stored at `CIOUSB+0x18`. |
| `ReadInterrupt(buf, seconds)` | `0x0f1c80` | 1 byte from the interrupt pipe: `ReadPipe` when `seconds` is 0, otherwise `ReadPipeAsync` plus a run loop for `seconds` |
| `GetInterruptVal()`, `SetInterruptVal()` | `0x05d0b0`, `0x08fdf0` | return or clear the stored byte at `CIOUSB+0x18`, no USB traffic |
| `ReadButtonID(*id, tries)` | `0x0f21b0` | bcdDevice ≥ `0x600`: `40 xx 0089` wIndex 0 with `00`, then `c0 xx 008a` wIndex 0, 1 byte, masked with plist `ButtonIORead`, repeated up to `tries` times; mapped to a button through plist `ButtonID`. The OpticFilm 120 plist has no `ButtonIORead`. |

For the OpticFilm 120 (`07b3:1406`) the macOS engine therefore never reads the interrupt endpoint `0x83`: it polls `c0 xx 008e` wIndex `0x21`, the same probe the 8200i SE driver uses during moves (`of120-capture-151.md`). Plustek's Windows driver of the capture used endpoint `0x83` instead.

Meaning of the values, as far as the code shows:

- `CAsic::MoveWithDetectSensor(expected, distance, delay)` (`0x05ca90`) starts a fast move and polls until the event byte equals `expected`, then switches the motor power bit off and sets FEEDL to 1. `CScan::StartMove` (`0x08e560`) passes the second value of plist key `MoveDetectSensor` (`1,64,100`, so `0x40`) for the first move and of `LoaderDetectSensor` (`1,32,240`, so `0x20`) for the second, a loader sensor move of 240 percent of `UnitDPI`, 2.4 inches. This matches the capture: move 1 ends with `0x40`, move 2 with `0x20`, each followed by the write that clears MTRPWR. Move 2's FEEDL 980 is 1488 steps for 2.4 inches at 620 steps per inch less four times `FMOVNO` 127 (`playbook.md`, "Moves and homing", part 2), and equals the 980 of `FilmLoaderOrigin` only by coincidence; the move to the loader origin is move 3. *(inference for the physical sensors behind the two bits)*
- `0x04`: no OpticFilm 120 code path waits for it. In `CScan::WaitInterruptEvent` (`0x0e3ef0`) value 4 is a button number that is only acknowledged. Its meaning on this scanner is not determined.
- `0x80` marks an ADF scanning interrupt in `WaitInterruptEvent` (other models).

## Reset, self tests

| Function | Address | Behaviour |
|---|---|---|
| `HardwareResetScanner()` | `0x0f8370` | `40 xx 008b` wIndex 4, 1 byte `00`. No caller in the binary. |
| `AsicSelfTest(...)` | `0x0f83e0` | returns 0, no USB traffic |
| `FlashSelfTest(...)` | `0x0f8410` | returns 1, no USB traffic |
| `SdramSelfTest(addr, len, block, pattern)` | `0x0f8430` | writes `pattern` to scanner SDRAM with `WriteData`, reads it back with `ReadData` and compares. Writes to the ASIC's memory, not to non-volatile storage. No caller in the binary. |

## Identity getters (no USB requests of their own)

| Function | Address | Returns |
|---|---|---|
| `GetPid()` | `0x05ca70` | idProduct, from IOKit `GetDeviceProduct` in `DealWithDevice` |
| `Bcd()`, `Bcd(value)` | `0x002da0`, `0x0051a0` | bcdDevice from IOKit `GetDeviceReleaseNumber`, stored at `CIOUSB+0x12`. `CScanApi::Register` overwrites it with plist key `BcdDevice` when that is positive (the OpticFilm 120 plist has none). |
| `GetSerialNumber()` | `0x038f40` | the IOKit `USB Serial Number` string read in `DealWithDevice`, or none |
| `IsHispeed()` | `0x0f08f0` | bcdDevice ≥ `0x200`: `c0 xx 008e` wIndex 0, 1 byte; high speed when bit 3 is clear. Cached at `CIOUSB+0x98`. |
| `Hispeed()` | `0x043f60` | the cached flag, no traffic |
| `SysClock()` | `0x058d10` | the last clock set, no traffic |

## Standby register

`CAsic::StandbyModeSel(enable)` (`0x061ac0`) and `CAsic::IsStandbyMode()` (`0x061d60`) use plist key `StandbyReg` (`0x31,0x80` for the OpticFilm 120) with `ReadReg` and `WriteReg`: enabling standby clears bit 7 of register `0x31`, disabling sets it, and the scanner counts as in standby mode while the bit is clear. Details in `../vendor-driver/macos.md`, "Device discovery and model selection".
