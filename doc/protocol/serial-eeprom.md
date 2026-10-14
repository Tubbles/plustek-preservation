# Serial EEPROM access (Plustek macOS engine)

How Plustek's macOS scanner engine would read a serial EEPROM through ASIC registers, what the register numbers collide with on the OpticFilm 120's register map, and how `tools/pi/eeprom_read.py` reads it. Static analysis only, nothing was executed.

Source: `PLK_A120.framework/Versions/A/ScanApi` from `OpticFilmOF120_V3100_12L.dmg` (engine version 1.4.27.4.0, see `../vendor-driver/macos.md`), x86_64 slice, analysed with Ghidra 12.1.4 (`../../tools/ghidra/README.md`). Addresses are offsets in the x86_64 slice. Every claim names the function it comes from; *(inference)* marks interpretation.

## Summary

- The engine has one EEPROM reader, `CAsic::ReadFromNVRAM` (`0x061120`), and nothing calls it. There is no EEPROM write function.
- Per 16-bit word it writes `0x80 | address` to register `0x8b`, reads the low byte from `0x8f` and the high byte from `0x8e`, and polls register `0x4f` until bit 4 clears. Before the loop it sets `EPROMSEL` (`0x0a` bit 3) and writes `0x30` to `0x8b`. Afterwards it writes `0x00` to `0x8b` and clears `EPROMSEL`.
- `0x30`, `0x80 | address` and `0x00` are the EWEN, READ and EWDS commands of a 93C46 in x16 organisation, written without the start bit *(inference, fits the datasheet exactly)*. How the ASIC clocks that byte out is unknown. Under other plausible clockings some READ bytes form EWEN, so only words 0 to 7 are safe to read before the clocking is known (section "Clocking of the 0x8b byte").
- On the OpticFilm 120's register map (`CGL126`) the same registers `0x8a` to `0x8f` are the exposure fields `EXPR` and `EXPG`, and the vendor configuration keeps `EPROMSEL` set during normal operation. Whether `0x8b`, `0x8e` and `0x8f` reach an EEPROM interface on this chip at all is open (last section).

## CAsic::ReadFromNVRAM (0x061120)

Prototype `CAsic::ReadFromNVRAM(unsigned char* buffer, unsigned short start, unsigned short count)`, exported as `__ZN5CAsic13ReadFromNVRAMEPhtt`. `buffer` receives `count` 16-bit words. The register numbers are immediates in the disassembly (`MOV ESI,0x8b` at `0x061189`, `0x06120a`, `0x0612fb`, `MOV ESI,0x8f` at `0x061228`, `MOV ESI,0x8e` at `0x061278`). The decompiler prints the two reads as `section_00000068.addr + 7` and `+ 6`, which is its rendering of small constants as Mach-O header fields.

| Step | Instruction | Action |
|---|---|---|
| 1 | `0x061172` | `_EPROMSEL(1, true, 0)`: set `EPROMSEL` and write register `0x0a` (section "EPROMSEL") |
| 2 | `0x061194` | `WriteReg(0x8b, 0x30)` |
| 3 | `0x06119d` | `CheckBusy`, return 0 if it fails |
| 4 | `0x0611c9` to `0x0611e3` | command byte = `0x80 \| (start & 0x3f)` |
| 5 | `0x061215` | loop, `count` times: `WriteReg(0x8b, command)` |
| 6 | `0x061233` | `ReadReg(0x8f)`, stored as the word (`0x06124a`) |
| 7 | `0x06124e` | `CheckBusy`, return 0 if it fails |
| 8 | `0x061283` | `ReadReg(0x8e)`, shifted left by 8 and added to the word (`0x061290` to `0x0612a0`) |
| 9 | `0x0612a4` to `0x0612b7` | address bits 5 to 0 of the command plus 1, modulo 64, bits 7 and 6 kept |
| 10 | `0x0612ba` | `CheckBusy`, return 0 if it fails |
| 11 | `0x061306` | after the loop: `WriteReg(0x8b, 0x00)` |
| 12 | `0x06130f` | `CheckBusy`, return 0 if it fails |
| 13 | `0x061338` | `_EPROMSEL(0, true, 0)`: clear `EPROMSEL` and write `0x0a`, return 1 |

Notes:

- Register `0x8f` gives the low byte, `0x8e` the high byte. The word is stored as a 16-bit value, so on x86_64 the buffer holds low byte, then high byte.
- No busy wait separates the command write (step 5) from the first data read (step 6). The first `CheckBusy` of a word comes after the low byte is read.
- The results of `WriteReg` and `ReadReg` are not checked: no test of `AL` follows the calls at `0x061194`, `0x061215`, `0x061233`, `0x061283` and `0x061306`. A failed read leaves the previous value of the local byte (`RBP-0x1d`) in the word. Only a failed `CheckBusy` ends the function.
- On that early return the function sends neither the `0x00` command nor the `EPROMSEL` clear, so `EPROMSEL` stays set.
- The address field is 6 bits wide and wraps from 63 to 0 within one call.
- The command is sent for every word, although the part could also be read sequentially (datasheet section 2.7, below).

## CAsic::CheckBusy (0x0614e0)

A loop: sleep 100 ms (`usleep(0x186a0)` at `0x06150b`), read register `0x4f` with `ReadReg` (`MOV ESI,0x4f` at `0x061523`, call at `0x06152e`), return 0 if the read fails, repeat while bit 4 (`AND EAX,0x10` at `0x061553`) is set, then return 1. There is no retry limit: if bit 4 stays set, the loop never ends. A read fails when the transfer is short or the second answer byte is not `0x55` (`ReadReg`, below).

Register `0x4f` has no field in the `CGL126` or `CGL128` tables (`gl128-registers.md`). The OpticFilm 120 plist base table (key `0` of `ScanInfoVID_07B3_PID_1406.plist`) sets `0x4f = 0x03`, and the register blast of the issue #151 capture writes the same (`of120-capture-151.md`, register table). That bit 4 means "Microwire transfer in progress" is read from this function only *(inference)*. `CRegistry::DeviceBusyReg` (`0x0dd350`, used in `CScan::SetScanParam`) is an unrelated plist-driven register and is not used here.

## EPROMSEL (register 0x0a bit 3)

`CAsic::_EPROMSEL(int value, bool write, int)` (`0x061350`) picks the chip class with a virtual call on its `CIOUSB` base (slot `0x10`, at `0x061382`) whose result it compares with the bcdDevice thresholds of the class selection (`../vendor-driver/macos.md`), so presumably bcdDevice *(inference: the slot was not resolved)*: ≥ `0x704` calls `CGL128::EPROMSEL` (`0x0732c0`), `0x703` `CGL125::EPROMSEL` (`0x0732e0`), `0x702` `CGL126::EPROMSEL` (`0x073300`), `0x600` to `0x701` `CGL846::EPROMSEL` (`0x0733c0`), and below `0x600` returns 1 without a call. The `CGL128` and `CGL125` versions only return 1. `ReadFromNVRAM` passes value 1, then 0, with `write` true and the last argument 0 both times (`0x061169` to `0x061172`, `0x06132f` to `0x061338`). The decompiler's `_EPROMSEL((int)this,true,1)` misplaces the arguments.

`CGL126::EPROMSEL` (`0x073300`), for the OpticFilm 120's bcdDevice `0x0702`:

1. Takes the host's shadow word of register `0x0a` (pointer at `this+0x10`, offset `0x14` = register × 2), clears bit 3 and ORs in `value << 3` (`0x07332b` to `0x073342`). The device is not read.
2. With `write` set, calls `CIOUSB::WriteRegs(0x0a, &shadow[0x0a], 1, true, 0)` (`0x073361` to `0x07337b`), which sends one `40 xx 0083` transfer with the pair (`0x0a`, low byte of the shadow word). Without `write` it only marks the register in the link list (`CRegister::SetLink`, call at `0x0733a2`).

So the other bits of `0x0a` come from the shadow, not from the scanner. The shadow is one array shared by the whole engine: `CGL126+0x8` and `CGL126+0x10` (constructor `0x0809c0`), `CIOUSB+0xe0` (`CIOUSB::CIOUSB`, `0x0ef520`) and `CRegistry+0xf4b0` (`CRegistry::CRegistry`, `0x089dc0`) all hold `CRegister::GetRegBuf()`, which is `CRegister+8` (`0x018ca0`). It holds what the open's register blast wrote. `CGL846::EPROMSEL` is the same code.

For the OpticFilm 120 the plist base table sets `0x0a = 0x48`, and the issue #151 capture's blast writes `0x0a = 0x48` (`of120-capture-151.md`, frame 17). Bit 3 is set, so **`EPROMSEL` is set during normal operation on this model**. `of120-capture-151.md` lists no change of `0x0a` for the scan blast (frames 191 to 214). After an open, `_EPROMSEL(1, ...)` would therefore send `0x48` unchanged and `_EPROMSEL(0, ...)` would send `0x40`. Other named bits of `0x0a` in `CGL126`: `ADFSEL` bit 5 (clear in `0x48`). Bit 6 is set but unnamed in Plustek's tables. SANE's GL124 header names bits 7 and 6 `SIFSEL`, bit 5 `SHEETFED` and bit 4 `LPWMEN` (below).

## Request framing

| Function | Address | Request |
|---|---|---|
| `CIOUSB::WriteReg(reg, uchar value, int)` | `0x0f2c50` | `40 a0 0083` (`0183` for `reg & 0x100`), wIndex 0, data `reg & 0xff, value`. The `int` argument is stored and then overwritten with 0 (`0x0f2c76`, `0x0f2c85`), so the first entry of the two-entry request table is always used. Also updates the shadow (`0x0f2d2b` to `0x0f2d36`). |
| `CIOUSB::ReadReg(reg, uchar*, int)` | `0x0f2670` | `c0 a0 008e` (`018e` for `reg & 0x100`), wIndex `(reg << 8) \| 0x22`, wLength 2. Fails unless the transfer succeeds and the second byte is `0x55` (`'U'`). The `int` argument is overwritten with 0 the same way. |
| `CIOUSB::ControlWrite`, `ControlRead` | `0x0f0eb0`, `0x0f0970` | bmRequestType `0x40` or `0xc0`, bRequest `0xa0`, success only when exactly wLength bytes moved |

This matches `usb-requests.md`, "Registers". The issue #151 capture sends the same requests with bRequest `0x04` for two-byte transfers. Concretely, with the capture's bRequest:

| Operation | Request |
|---|---|
| write `0x8b` | `40 04 0083`, wIndex 0, data `8b vv` |
| write `0x0a` | `40 04 0083`, wIndex 0, data `0a vv` |
| read `0x8f`, `0x8e`, `0x4f`, `0x0a` | `c0 04 008e`, wIndex `0x8f22`, `0x8e22`, `0x4f22`, `0x0a22`, 2 bytes, answer `vv 55` |

## Other code that touches these registers

Method: Ghidra references to each function, a search for each function address as an 8-byte value in the whole image, and a list of all 1185 calls to `CIOUSB::WriteReg`, `ReadReg`, `WriteRegs`, `ReadRegs`, `WriteRegBit` and `ReadRegBit` with the register number taken from the last `MOV ESI, immediate` before the call (two helper Ghidra scripts that are not in the repository, outputs in `work/re/eeprom/`, plus `FindScalars.java` for `0x8e`, `0x8f` and `0x4f`).

- Callers: `ReadFromNVRAM` has none. Its only references are the export entry and the function start table in `__LINKEDIT`. `CheckBusy` is called only from `ReadFromNVRAM` (`0x06119d`, `0x06124e`, `0x0612ba`, `0x06130f`), `_EPROMSEL` only from `ReadFromNVRAM` (`0x061172`, `0x061338`), and the four class methods only from `_EPROMSEL`. The 8-byte search finds the addresses only in `__LINKEDIT` symbol tables, and Ghidra shows no data reference from `__DATA`, so there is no vtable slot for any of them.
- Calls with an immediate register `0x8b`, `0x8e`, `0x8f` or `0x4f`: only in `ReadFromNVRAM` and `CheckBusy`. `0x8f` also appears in `CGL846::PREFED` (`0x04dee7`), a field of another chip's map.
- Calls with an immediate register `0x0a`: only the `ADFSEL` accessors (`WriteRegs` and `ReadRegs` in `CGL128`, `CGL125`, `CGL126` and `CGL846`, `0x04eabb` to `0x04ef04`) and the two `EPROMSEL` methods (`0x07337b`, `0x07343b`). `ADFSEL` writes the whole shadow byte of `0x0a`, `EPROMSEL` bit included.
- Field accessors that cover the same registers: `CGL126::EXPR` (getter `0x06e260`, setter `0x06f490`) is `0x8a` to `0x8c` and `CGL126::EXPG` (`0x06e4a0`, `0x06f800`) is `0x8d` to `0x8f`, 24-bit big-endian (`gl128-registers.md`). They go through `ReadRegs` and `WriteRegs` with base `0x8a` or `0x8d`. The register blast (`CIOUSB::WriteAllReg`) also writes any of these registers that the shadow marks as changed.
- 213 of the 1185 calls take the register number from another register (mostly plist-driven selectors such as `CAsic::CisPowerSel`, `MotorPowerSel`, `StandbyModeSel`) and were not resolved. The register-valued strings of the OpticFilm 120 plist name only `0x31`, `0x33`, `0x36`, `0x50`, `0x51`, `0x5d`, `0x5e`, `0x107` and `0x108`.
- No write path: no function name contains NVRAM, EEPROM or EPROM other than the ones above, and no other code writes an immediate register `0x8b`. So none of WRITE (`0x40 | a`), ERASE (`0xc0 | a`), ERAL (`0x20`) or WRAL (`0x10`) is sent to `0x8b` from a constant. Writes with computed register numbers or through the shadow are not covered by this scan.

## SANE and pyopticfilm

SANE: `work/downloads/sane-project/sane-backends-git` (master `a8676a6f`, 2026-10-12), `backend/genesys/`. pyopticfilm: the submodule at `32dc576`.

- Neither project contains "eeprom", "eprom" or "nvram" (case-insensitive search over `backend/genesys/` and all of pyopticfilm's Python files).
- GL124 (`gl124_registers.h` lines 103 to 107): `0x0a` holds `SIFSEL` (`0xc0`), `SHEETFED` (`0x20`) and `LPWMEN` (`0x10`). Bit 3 is not named. `gl124.cpp` reads `0x0a` to choose the analogue front end from `SIFSEL` (lines 407 to 410) and initialises `0x0a = 0xc0`, `0x4f = 0x00`, `0x8b = 0x8e = 0x8f = 0x00` (lines 93, 144, 221 to 225). `REG_EXPR` is `0x8a` and `REG_EXPG` is `0x8d` (`gl124_registers.h` lines 270 and 271), the same positions as Plustek's `CGL126` map.
- GL846 and GL847: `0x0a` has only `LPWMEN` (`gl846_registers.h` line 107, `gl847_registers.h` line 105), initialised to `0x00` (`gl846.cpp` line 94, `gl847.cpp` line 86). Neither header names `0x4f`, `0x8b`, `0x8e` or `0x8f`.
- GL845: no file of its own in this checkout. It appears only in comments and the model enum.
- GL128 (`gl128.cpp`, derived from pyopticfilm): boot values `0x0a = 0x40` and `0x4f = 0x03` (lines 1402 and 1448), and `0x8a` to `0x92` written in the feed set-up (lines 208 to 209, 1322 to 1323).
- pyopticfilm `src/pyopticfilm/device/gl128_common.py`: `INIT_REGS` has `0x0A: 0x40` and `0x4F: 0x03` (lines 33 and 41), `SCAN_REGS` sets `0x8A` to `0x8F` to 0 (line 97). These are 8200i SE values, with `EPROMSEL` clear.

## Microwire commands of a 93C46 (x16)

Source: Microchip, "93AA46A/B/C, 93LC46A/B/C, 93C46A/B/C 1K Microwire Compatible Serial EEPROM", DS20001749K, https://ww1.microchip.com/downloads/en/DeviceDoc/20001749K.pdf. Table 1-3 (x16 organisation, 93XX46B or 93XX46C with ORG = 1), with the eight bits after the start bit as one byte:

| Instruction | Start bit | Opcode | Address | Byte after the start bit | Data |
|---|---|---|---|---|---|
| READ | 1 | `10` | A5 to A0 | `0x80 \| a` | D15 to D0 out, after a dummy zero bit |
| EWEN | 1 | `00` | `11XXXX` | `0x30` | |
| EWDS | 1 | `00` | `00XXXX` | `0x00` | |
| WRITE | 1 | `01` | A5 to A0 | `0x40 \| a` | D15 to D0 in |
| ERASE | 1 | `11` | A5 to A0 | `0xc0 \| a` | |
| ERAL | 1 | `00` | `10XXXX` | `0x20` | |
| WRAL | 1 | `00` | `01XXXX` | `0x10` | D15 to D0 in |

From the same datasheet:

- Section 2.6: the part "powers up in the Erase/Write Disable (EWDS) state". Every programming mode needs EWEN first, and "Execution of a READ instruction is independent of both the EWEN and EWDS instructions". Section 2.3 says the same for power-up.
- Section 2.7: a dummy zero bit precedes the 16 data bits, and with CS held high the part outputs the following words sequentially.

The three bytes `ReadFromNVRAM` writes to `0x8b` are EWEN, READ and EWDS in this encoding. The 6-bit address mask and the 16-bit words fit the x16 organisation. The x8 organisation has 7 address bits (Table 1-4), so its commands need nine bits after the start bit and do not fit one 8-bit register value. Larger Microwire parts were not checked. So, if `0x8b` is a Microwire command register, the start bit, the dummy bit and the clocking are done by the ASIC and the part is a 93C46 in x16 organisation *(inference)*. The EWEN before the reads is not needed for READ.

## Clocking of the 0x8b byte

How the ASIC shifts the byte written to `0x8b` out to the chip is not known. The reading above assumes clocking A. Four clockings were checked with a small decoder. A 93C46 takes the first 1 on DI while CS is high as the start bit (datasheet section 2.1), so without a start bit from the ASIC, leading zeros of the byte are skipped. The bits after the byte were taken as all 0 and as all 1.

| Clocking | Bits sent |
|---|---|
| A | a start bit from the ASIC, then the byte MSB first (the reading above) |
| B | the byte MSB first, no added start bit: bit 7 of a READ byte becomes the start bit |
| C | a start bit from the ASIC, then the byte LSB first |
| D | the byte LSB first, no added start bit: its first 1 becomes the start bit |

The bytes of a run over words 0 to 7, as the chip would decode them:

| Word | Byte | A | B | C | D, line low after the byte | D, line high |
|---|---|---|---|---|---|---|
| 0 | `0x80` | READ 0 | EWDS | EWDS | EWDS | ERASE `0x3f` |
| 1 | `0x81` | READ 1 | EWDS | READ `0x01` | EWDS | EWDS |
| 2 | `0x82` | READ 2 | EWDS | WRITE `0x01` | EWDS | EWDS |
| 3 | `0x83` | READ 3 | EWDS | ERASE `0x01` | READ `0x02` | READ `0x03` |
| 4 | `0x84` | READ 4 | EWDS | ERAL | EWDS | EWDS |
| 5 | `0x85` | READ 5 | EWDS | READ `0x21` | WRITE `0x02` | WRITE `0x03` |
| 6 | `0x86` | READ 6 | EWDS | WRITE `0x21` | READ `0x04` | READ `0x07` |
| 7 | `0x87` | READ 7 | EWDS | ERASE `0x21` | ERASE `0x02` | ERASE `0x03` |
| | `0x00` | EWDS | nothing, or ERASE `0x3f` with the line high | EWDS | nothing | ERASE `0x3f` |

None of these bytes forms EWEN under any of the four clockings, as long as the data line stays at one level after the byte (low or high). If the line changes level after the byte, `0x80` under D and `0x00` under B and D are decided entirely by those later bits and can form EWEN. Under C and D some of them form WRITE, ERASE and ERAL, which a 93C46 ignores unless EWEN came first (datasheet section 2.6). So a run over words 0 to 7 cannot change the chip, provided that (1) the ASIC clocks the byte in one of these four ways, and (2) the chip is write-disabled when the run starts. (2) holds after power-up and stays true until something sends EWEN. A wake from standby may not remove power from the EEPROM, so unplugging the 24 V adapter once before the first run makes (2) certain. In the shared-register reading (section "Conflict with the exposure registers"), a vendor scan since the last power-up could have done that.

Over all 64 words, READ bytes form EWEN at:

| Clocking | Words whose READ byte forms EWEN | What follows |
|---|---|---|
| A | none | |
| B | `0x18` to `0x1f` | WRITE for words `0x20` to `0x3f` in the ascending pass, ERAL (`0x10` to `0x17`) in the descending pass. Words `0x08` to `0x0f` form WRAL. |
| C | `0x0c`, `0x1c`, `0x2c`, `0x3c` | WRITE, ERASE and ERAL bytes in the following words |
| D | `0x19`, `0x32`, `0x39`, and `0x10` with the line high | WRITE and ERASE bytes |

So a 64-word run is only safe under clocking A. `tools/pi/eeprom_read.py` therefore reads words 0 to 7 by default and needs `--words 64` for the rest. Reading the result of the first run:

- Every word equal, other than `ffff` (exit 15): `0x8f` and `0x8e` do not follow the address. That is what the exposure-register reading predicts. Stop here.
- Every word `ffff` (exit 15): no chip, a blank chip, or no READ formed (clockings B and D form almost none in this range). The run cannot tell these apart.
- The passes differ (exit 12): under C and D most bytes form no READ, so those words show whatever the data registers held before, which differs between the ascending and the descending pass. Clocking A gives the same eight words in both passes *(inference: depends on what the ASIC puts in the data registers when the chip sends nothing)*.
- The passes agree and the eight words look like data, not mostly `ffff` or `0000` with a few exceptions: this fits clocking A but does not prove it. Only then is a 64-word run worth considering, and the owner decides.

## Conflict with the exposure registers

Two observations do not fit the reading of `0x8b`, `0x8e` and `0x8f` as an EEPROM interface on the OpticFilm 120:

1. In `CGL126`, the class the engine uses for this scanner, `0x8a` to `0x8c` is `EXPR` and `0x8d` to `0x8f` is `EXPG` (`gl128-registers.md`), and SANE's GL124 has the same positions.
2. `EPROMSEL` is set in normal operation (`0x0a = 0x48` from the plist and in the capture), and in that state the capture's scan blast writes exposure values there: `0x8a 00`, `0x8b 55`, `0x8c 00`, `0x8d 00`, `0x8e 55`, `0x8f 00` (`of120-capture-151.md`, frames 191 to 214).

Possible readings, none confirmed:

- `ReadFromNVRAM` was written for another chip generation and its register numbers do not apply to `CGL126`. Nothing in the binary runs it, and it has no bcdDevice branch of its own, so the code does not show that it was ever used on this chip *(inference)*. In that case `0x8b` is the middle byte of `EXPR`, `0x8e` and `0x8f` are the two low bytes of `EXPG`, and a reader gets the same word for every address.
- The registers are shared and something other than `EPROMSEL` decides their meaning. If `0x8b` were the Microwire command register while `EPROMSEL` is set, the scan blast's `0x8b = 0x55` would clock out a WRITE (`01`) to word `0x15` under clocking A (section "Clocking of the 0x8b byte"), which a 93C46 ignores while write-disabled (datasheet section 2.6) *(inference)*. An exposure byte of `0x30` to `0x3f` in `0x8b` would then form EWEN, so in this reading a vendor scan could leave the chip write-enabled until it loses power *(inference)*.

Bit 4 of `0x4f` as a busy flag comes from `CheckBusy` alone.

## Reading the EEPROM over USB

`tools/pi/eeprom_read.py` runs `ReadFromNVRAM`'s sequence without the EWEN, over words 0 to N - 1 (`--words N`, default 8, at most 64, see section "Clocking of the 0x8b byte"). Its docstring lists the steps, the set-up on the Pi and the exit codes. The requests it can send:

1. Reads of `0x31`, `0x34`, `0x4f`, `0x8e`, `0x8f` (logged), then `0x0a`.
2. If bit 3 of `0x0a` is clear: write `0x0a` with only bit 3 set in addition, then read `0x0a` back. A mismatch stops the run (exit 14). If bit 3 is already set (the vendor's value), no write.
3. Poll `0x4f` until bit 4 is clear.
4. For words 0 to N - 1, ascending, then again descending: write `0x8b = 0x80 | address`, read `0x8f`, poll `0x4f`, read `0x8e`, poll `0x4f`.
5. Write `0x8b = 0x00` (EWDS), poll `0x4f`, then write `0x0a` back to the value read if it was changed, and read it back. The write-back also runs after any error, best effort.

The read-back of `0x0a` is there because a read of `0x31` on this chip returns pin levels, not the written value (the capture's blast writes `0x31 = 0xfc` and `0xbe` reads back, `of120-capture-151.md`, start-up step 13), so a read of `0x0a` might not return the latch either.

Every busy poll sleeps 100 ms first, as `CheckBusy` does, and a wait gives up after 20 polls. The tool refuses any other register write or read before the transfer is sent: `0x8b` only with `0x80` to `0xbf` or `0x00`, `0x0a` only with bit 3 changed from the value read. No byte it sends is EWEN under clocking A. Whether a byte could still be clocked out as EWEN depends on the clocking: with the default 8 words it cannot under any of the four clockings considered while the data line stays at one level after the byte, with 64 words it can under B, C and D. That a write or erase opcode then takes no effect also rests on the chip being write-disabled when the run starts (section "Clocking of the 0x8b byte").

The log records whether `0x8f` and `0x8e` follow the address (number of distinct low and high bytes, and a note when all words are equal). A uniform result (every word equal) is reported separately: all `ffff` means no chip, a blank chip or a data line stuck high, all `0000` a data line stuck low, any other value that the data registers do not follow the address, which is what the exposure-register reading predicts.

Before a run on the Pi: create `~/plustek-preservation/probe-disabled`, and make sure `keep_awake.py` does not run on this wake, since it writes `0x31` and `0x34` and `0x34` should keep its power-on value. In the current `watch-scanner.sh` that means `~/plustek-preservation/keep-awake-enabled` must not exist. Start the run after the watcher has logged "probe disabled" (or "keep awake exit") for this connection. The tool refuses to start while `probe-disabled` is missing or a process with an argument ending in `probe_readonly.py` or `keep_awake.py` runs.

Caveats:

- The sequence has not been run on hardware. Plustek's engine never runs it either.
- The tool runs without the open's register blast and clock set-up, like `flash_dump.py`. Whether the ASIC's EEPROM interface, if any, needs that set-up is unknown.
- The tool writes back the value of `0x0a` it read, with only bit 3 changed. The vendor writes its shadow value (`0x48` or `0x40`) instead. If a read of `0x0a` returns pin levels for some bits, the value written back can differ from the original latch in those bits. The read-back only checks that a read returns the value just written.
- If `0x8b` is the `EXPR` middle byte, the run leaves it at `0x00`. The vendor's scan set-up rewrites the exposure registers before every scan (capture frames 191 to 214).
