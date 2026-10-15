# Driver playbook: Plustek's engine mapped onto pyopticfilm

Plustek's own driver, read as the playbook for the OpticFilm 120 (`../work/0012-driver-playbook.md`). Each section takes one topic, derives the requests from the macOS engine's code first, checks them against the issue #151 capture second, and maps them onto pyopticfilm's GL128 code third, so that the OpticFilm 120 lands in pyopticfilm as a model configuration rather than as a replay tool. Each section ends with the pyopticfilm change it implies. Topics, in the order of the work item: standby (below), then open, moves and homing, and scan.

Conventions:

- Addresses are offsets in the x86_64 slice of the macOS `ScanApi` 1.4.27.4.0 (`../vendor-driver/macos.md`). Decompiled functions are cited by file name and line. The files are in `work/re/decomp-x86_64/`, the disassembly in `work/re/disasm-x86_64/` (untracked, made as described in `../../tools/ghidra/README.md`).
- "The plist" is `ScanInfoVID_07B3_PID_1406.plist` of the macOS package (`../vendor-driver/macos.md`, "Layout"), cited by line. It is the only configuration the engine loads for the OpticFilm 120 (`../vendor-driver/macos.md`, "Which configuration file").
- Capture frames are those of `of120-capture-151.md` (decoded listing in `work/captures/151/annotated.txt`).
- pyopticfilm is cited at submodule commit `32dc576` (release 1.3.5), paths relative to `pyopticfilm/src/pyopticfilm/`.
- The OpticFilm 120 runs the engine's `CGL126` class, field positions from `gl128-registers.md`. Data registers and output enables pair up as `0x31`/`0x34` (GPIO1 to 8, GPOE1 to 8), `0x32`/`0x35` (9 to 16), `0x33`/`0x36` (17 to 24) and `0x37`/`0x38` (25 to 32). That a set GPOE bit makes the pin an output is read from the names *(inference)*.
- *(inference)* marks an interpretation, not something read in the code or seen on the wire.

## Standby

In short: the engine's only standby line is GPIO8 (`0x31` bit 7, plist `StandbyReg`). At open the register blast sets it high together with its output enable (`0x34` bit 7), then `Register` pulls it low for 10 ms and high again. While the engine runs, a 5 s tick reads `0x31` and sets bit 7 again only when it finds it clear. At close the engine clears it. No other GPIO and no other register is treated as a host-present or wake signal. On the owner's unit, GPIO8 driven high without the pulse did not hold the unit, the full open with the pulse did, so the smallest write set to try is those same two writes plus the engine's pulse. pyopticfilm has no standby handling, which matches the engine for the 8200i SE (its configuration has no `StandbyReg`). An OpticFilm 120 model needs an open hook and a close hook.

### 1. GPIO writes at open

**How the engine writes GPIO registers.** There are three ways, and this model uses two of them.

- Register shadow and blast. `CRegistry::ReadSettings(-1,-1,-1,-1)` (`0x08c260`) calls `CRegistry::ReadKey(NULL)` (`0x08b090`). That clears the register shadow and the property array (`CRegistry__ReadKey@0008b090.c` lines 66 to 68), copies the base blob `0` into the shadow and marks each register for the next blast with `CRegister::SetLink` (lines 122 to 137), then applies every key that names a register. A key `rr.mm` sets the bits of mask `mm`: `(old & (mm ^ 0xffff)) + value` (lines 238 to 245). A key `rr` alone overwrites from register `rr` on (lines 247 to 254). Named keys such as `StandbyReg` go into the property array through the name table `m_prop` (lines 197 to 220), so a key the plist lacks reads 0 (the clear at line 68, and in `CRegistry__CRegistry@00089dc0.c` line 35). `CIOUSB::WriteAllReg` (`0x0f3650`) sends every marked register in marking order and clears the marks (`CIOUSB__WriteAllReg@000f3650.c` lines 34 to 40).
- Selectors keyed by the plist: they read a register, change the bits a key names and write it back (`CAsic::LoaderEjectSel`, `CAsic::StandbyModeSel` and the others in the table below).
- Named field setters (`_GPIO8`, `_GPOE8`, ...), which change the shadow and either write the register or mark it (`CGL126__GPIO8@00075c20.c` lines 15 to 21). None writes a GPIO register on this model's open path. The only ones in the call tree are `_GPIO22` and `_GPIO23`, behind plist key `CPLDDpiSet`, which the plist lacks (`CScanApi__SoftwareResetScanner@000338a0.c` lines 53 to 57), and `_GPOADF`, a stub that returns 1 in `CGL126` (`CGL126__GPOADF@0004f7f0.c`). The interrupt thread started at open reads `0x37` once through the getter `_GPIO25(…, 1)` (`CScan__WaitInterruptEvent@000e3ef0.c` line 91, `CGL126__GPIO25@000ebb80.c` lines 13 to 17), a read only.

**The GPIO area after `ReadKey`.** Blob and patches decoded from the plist (lines 7 to 28) with `python3 -I`, against the capture's blast (frame 21, `of120-capture-151.md`, "The register blast") and the owner's unit before any write (`../hardware/probes/20261015T061444Z-vendor-open.jsonl`, record `registers_before_open`):

| Register | Blob `0` | Patch key (plist line) | Result | Frame 21 | Outputs enabled and level driven | Owner's unit before any write |
|---|---|---|---|---|---|---|
| `0x30` | `0x6e` | `30.0f` = `0x0f` (13) | `0x6f` | `0x6f` | bits 5 and 6 are `GPOM11` and `GPOM12`, bits 0 to 3 (the patch) have no accessor | |
| `0x31` | `0x7c` | `31.80` = `0x80` (15) | `0xfc` | `0xfc` | GPIO8 = 1, the other bits are inputs | `0xbc` |
| `0x32` | `0x6b` | | `0x6b` | `0x6b` | GPIO9 to 15 = 1, 1, 0, 1, 0, 1, 1 | |
| `0x33` | `0x0c` | `33.02` = `0x02` (17), `33.c0` = `0x00` (19) | `0x0e` | `0x0e` | GPIO19 to 24 = 1, 1, 0, 0, 0, 0 | `0x1e` |
| `0x34` | `0x00` | `34.80` = `0x80` (21) | `0x80` | `0x80` | GPOE8 | `0x00` |
| `0x35` | `0x7f` | | `0x7f` | `0x7f` | GPOE9 to 15 | |
| `0x36` | `0xfc` | | `0xfc` | `0xfc` | GPOE19 to 24 | `0x00` |
| `0x37` | `0x30` | `37.20` = `0x20` (23) | `0x30` | `0x30` | GPIO25, 26, 27, 29, 30, 31 = 0, 0, 0, 1, 1, 0 | |
| `0x38` | `0x57` | `38.20` = `0x20` (25) | `0x77` | `0x77` | GPOE25, 26, 27, 29, 30, 31 | |
| `0x39` | `0x02` | | `0x02` | `0x02` | `GPO34` = 1 | |
| `0x3a` | `0x00` | | `0x00` | `0x00` | `GPOLED8` to `GPOLED25` clear | |
| `0x3b` | `0xff` | `3b` = `0xff` (27) | `0xff` | `0xff` | `VRMOVE`, `VRSCAN` | |
| `0x3c` | `0xff` | | `0xff` | `0xff` | | |

So the capture's GPIO bytes are the plist's blob with its patches, byte for byte. Keys `114` and `115` (`0x80` each, plist lines 9 to 12) are register keys too and give the separate transfer of frame 33. Every one of the 12 blasts in the capture writes `0x31 = 0xfc` and `0x34 = 0x80` (`work/captures/151/annotated.txt`, for example frames 21, 165 and 7399).

**The open, call by call.** `CScanApi::Register` (`0x01da80`) with this plist. Line numbers are in `CScanApi__Register@0001da80.c`, call addresses from `CScanApi__Register@0001da80.s`. Calls without a GPIO effect are left out unless `tools/pi/vendor_open.py` replays them.

| # | Engine call | GPIO effect with this plist | Keys | Capture frames | In `vendor_open.py` |
|---|---|---|---|---|---|
| 1 | `CIOUSB::InitInterrupt`, line 67 (`0x01dc18`) | none. Reads `0x8a` index `0x26fe` and writes it back as 0 through `0x8b` only when bit 0 is set (`CIOUSB__InitInterrupt@000f86a0.c` lines 15 to 19) | | 15 | yes (read). The owner's unit answers `00`, so no write is due |
| 2 | `SoftwareResetScanner`, line 69 (`0x01dc2b`) | `_SCANRESET(false, 1)` writes `0x0e = 0x00` (line 40, `CGL126__SCANRESET@0004f270.c`), `ReadSettings` (41), first full blast (58) with the GPIO area above, clocks and DRAM refresh, `SPI_init` and `SFlash_RDID` (105), `_ADFSEL(false, 0)` and a `WriteAllReg` of what was marked since (117 to 119), `InitStandbyModelOffTimeInfo` (128) | `0`, the patches | 17 to 71 | blast yes, `0x0e` no |
| 3 | `ReadSettings` again (71), second full blast after the lock (143, `0x01e033`) | the same GPIO bytes again | `0`, the patches | none | no |
| 4 | `WaitMotorStop`, `LampOn(false)`, `WriteAllReg`, `CAfe::_aSoftwareReset`, `WriteAllAfe` (200 to 254) | none | `LampType 1` (plist 132 to 133) | 73 to 112 | yes |
| 5 | `CAsic::SetScannerReady`, 255 (`0x01e5d5`) | none: `DeviceReadyReg` absent (`CAsic__SetScannerReady@0006bd90.c` line 22) | | | |
| 6 | `CAsic::LoaderEjectSel(true)`, 261 (`0x01e62d`) | `WriteRegBit(0x36, 1, 1, 1)`: read `0x36`, set bit 1 (GPOE18), write (`CAsic__LoaderEjectSel@0006b140.c` line 35, `CIOUSB__WriteRegBit@000f6490.c` lines 31 to 36). Then read `0x33`, set bit 1 (GPIO18) if clear, write (lines 48 to 69) | `LoaderEjectSwitchIO = 0x36,1`, `LoaderEjectSwitch = 0x33,0x02,1` (plist 146 to 149) | 113 to 124: `0x36` `0xfc` → `0xfe`, `0x33` `0x0e` → `0x0e` | yes (115, 121) |
| 7 | `CleanUserData(0)`, `CleanUserData(1)`, 270 and 271 | none: `DisableUserData = 1` (plist 82 to 83) returns at once (`CAsic__CleanUserData@0005b150.c` lines 19 to 21) | | | |
| 8 | `AfeClockSel(false)`, `CisPowerSel(false, …)`, `MotorPowerSel(false, …)`, `AdfCISClockSel(false)`, 272 to 275 | none: each acts only when its key is set (`CAsic__AfeClockSel@00061580.c` line 24, `CAsic__CisPowerSel@0005dd10.c` lines 31 to 65, `CAsic__MotorPowerSel@0005e990.c` lines 29 to 57, `CAsic__AdfCISClockSel@00061ed0.c` line 31), and the plist has none of `AfeClockSwitch`, `CisPowerSwitch`, `CISPowerFBSel`, `CISPowerAdfFrontSel`, `CISPowerAdfRearSel`, `MotorPowerFBSel`, `MotorPowerAdfSel`, `MotorPowerSheetfedSel`, `AdfCISClockSwitch` | | | |
| 9 | `CIOUSB::IsHispeed`, 276 | none. Reads `0x8e` index 0 (`CIOUSB__IsHispeed@000f08f0.c`) | | 125 | yes |
| 10 | `StandbyModeSel(true)`, 278 (`0x01e784`); `_usleep(10000)`, 279 (`0x01e78e`); `StandbyModeSel(false)`, 280 (`0x01e7a6`) | read `0x31`, clear bit 7, write; 10 ms; read `0x31`, set bit 7, write. `local_13 = local_13 & ((byte)*(undefined4 *)(lVar6 + 4) ^ 0xff);` and `local_13 = local_13 \| (byte)*(undefined4 *)(lVar6 + 4);` (`CAsic__StandbyModeSel@00061ac0.c` lines 57 and 33). The optional second register pair of `StandbyReg` is 0, so lines 38 to 48 and 62 to 72 do nothing | `StandbyReg = 0x31,0x80` (plist 735 to 736) | 127 to 138, 13.3 ms from write to write | yes (129, 135) |
| 11 | `LoaderInterruptReg` block (282 to 336), `HolderInterruptSel(true)`, 337 (`0x01eaf2`) | none: `LoaderInterruptReg` absent (`CAsic__HolderInterruptSel@0006c0f0.c` line 25) | | | |
| 12 | second block after the lock (338 to 465): `WriteAllReg`, AFE, clocks, `IsHispeed`, `LampOn(false)`, `StandbyModeControl(false)` (419, `0x01ef52`), `SFlash_RDID`, `LoaderEjectSel(true)` (462, `0x01f14b`) | `0x31` rewritten with bit 7 set (already set), `0x36` bit 1 and `0x33` bit 1 rewritten (already set) | `StandbyReg`, `LoaderEject*` | none | no |

**What `vendor_open.py` lacks, and where its writes come from.** In the GPIO area the table lacks only repeats of values already set: the second full blast (row 3) and the second block's `StandbyModeControl(false)` and `LoaderEjectSel` (row 12). Outside it, the table lacks the `0x0e = 0x00` write (row 2) and the second clock, DRAM and flash ID set-up (rows 3 and 12, `serial-flash.md`, "When the engine touches the flash at open"). The capture has none of these (frames 15 to 138), which is why the replay lacks them. The Open step settles those differences. Every GPIO value the table writes comes from the plist through the engine: frame 21's GPIO bytes from blob `0` and the patches, frame 115 from `LoaderEjectSwitchIO`, frame 121 from `LoaderEjectSwitch`, frames 129 and 135 from `StandbyReg`. The other table writes map as in `../vendor-driver/macos.md`, "What the engine sends at open": blast and `0x114`/`0x115` (frames 17 to 33) from blob `0` and keys `114`, `115`; clocks and DRAM refresh (37 to 53); `SPI_init`, `SFlash_RDID` and `ReadIRScalingInfo` (57 to 71, keys `FlashRAM`, `Enable_IR_Scaling`, `flash_addr_Postive_IR_Scaling`); `WaitMotorStop` (73, 75); `LampOn(false)` (77); AFE reset and `WriteAllAfe` (81 to 112) from key `@` (plist lines 31 to 32: AFE 0 = `0xf8`, AFE 1 = `0x80`, the rest 0) *(inference for `@`: the decompiler shows the key strings of `ReadKey` only as `cf__`)*. `vendor_open.py` writes the capture's constants `0x3e` and `0xbe`, while the engine writes the value it read with bit 7 cleared or set. The owner's unit read `0xbc` and `0x3c` there (`../hardware/probes/20261015T061444Z-vendor-open.jsonl`, frames 127 and 133), so the replay's values differ from the engine's only in bit 1, an input (GPOE2 clear) *(inference)*.

### 2. The engine's standby model

- Line and polarity. `StandbyModeSel(true)` clears the `StandbyReg` mask in `0x31`, `StandbyModeSel(false)` sets it, and both do nothing when `StandbyReg` is 0 (`CAsic__StandbyModeSel@00061ac0.c` line 24). `CAsic::IsStandbyMode` (`0x061d60`) reads `0x31` and reports standby while the bit is clear (`CAsic__IsStandbyMode@00061d60.c` lines 28 to 32 and 45 to 50). `CScanApi::StandbyModeControl` (`0x038e50`) wraps it: `true` sets the engine's flag `this[0x1b8]`, `false` clears it and sets `_g_fSkipStandbyOffTimer` (`CScanApi__StandbyModeControl@00038e50.c` lines 8 to 17).
- Timer. `CScanApi::InitStandbyModelOffTimeInfo` (`0x022ee0`, called at the end of `SoftwareResetScanner`) needs `StandbyReg` (line 17), reads `StandbyOffTime` (15, plist lines 59 to 60), sets the limit to `(StandbyOffTime - 5) * 60000` ms with `StandbyOffTime` raised to at least 5, the step to 5000 ms, and starts the timer (`CScanApi__InitStandbyModelOffTimeInfo@00022ee0.c` lines 23 to 31). `CNotify::SetStandbyModeTimer` (`0x0889c0`) creates a run loop timer with interval `0x4014000000000000`, 5.0 s. `Timer` (`0x088ab0`) calls the notify callback with `0xff`, and `CScanApi::EventHandler` (`0x038600`) runs `TestUnitReady`, then `SetStandbyOffTime` (`CScanApi__EventHandler@00038600.c` lines 16 to 19).
- Each tick, `CScanApi::SetStandbyOffTime` (`0x0387a0`) works only while no scan runs and `_g_fSkipStandbyOffTimer` is clear (`CScanApi__SetStandbyOffTime@000387a0.c` line 23), and only when `TestUnitReady` returns ready (line 25). Then:
  - `LoaderReadyReg = 0x31,0x04` (plist lines 152 to 153): `CAsic::IsLoaderReady` (`0x06b020`) reads `0x31` and reports ready unless bit 2 (GPIO3) reads set twice (`CAsic__IsLoaderReady@0006b020.c` lines 24 to 39). A ready holder ends the tick: the engine sets bit 7 if `IsStandbyMode` finds it clear and resets the idle count (lines 29 to 39).
  - `LoaderSensorReg` would do the same with the holder's home sensor (lines 43 to 55). The plist has no such key.
  - Before the limit, if the engine's flag is set or `IsStandbyMode` finds bit 7 clear, `StandbyModeControl(false)` sets it and resets the count (lines 78 to 86).
  - The count grows by 5000 (line 90). At the limit the engine calls `StandbyModeControl(true)` and logs `"SetStandbyOffTime : scanner set into standby mode in 5 min !\n"` (lines 91 to 95), and it clears the bit again whenever it later finds it set (lines 97 to 106).
  - While a scan runs, or on the first tick after any `StandbyModeControl(false)`, the tick only resets the count and clears the skip flag (lines 129 to 132). So every `StandbyModeControl(false)` restarts the 10 minute idle count.
  - Per tick with this plist, the engine therefore sends reads of `0x31` and, only when bit 7 is clear or at the limit, one read-modify-write of `0x31` bit 7. It writes no other register and sends no pulse.
- `CScanApi::TestUnitReady` (`0x0232f0`) sends nothing on the tick path. It reads and clears `CNotify::m_Notice` (`CScanApi__TestUnitReady@000232f0.c` lines 30 and 31) and acts on bits `0x21`, `0x12` and `4` (lines 32, 62 and 96). The decompiled code has three writers of `m_Notice`: `DeviceAttach` (`0x0886a0`) ORs in `0x10`, `DeviceDetach` (`0x088710`) `0x20`, `Timer` `0x3000` (`DeviceAttach@000886a0.c` line 13, `DeviceDetach@00088710.c` line 15, `Timer@00088ab0.c` line 10). The tick's `0x3000` matches none of the three tests. After a USB attach (`0x10`) it runs `Unregister` and the whole `Register` again (lines 62 to 95), so the engine meets a unit that has re-enumerated with a new open, pulse included. Its `StandbyModeControl(false)` (line 51) needs bit 0 of `m_Notice`, which none of the three writers sets, so on macOS it does not run *(inference: a writer that Ghidra did not decompile would change this)*. `../vendor-driver/macos.md`, "Standby", lists `TestUnitReady` among the callers without that condition.
- The interrupt thread `CScan::WaitInterruptEvent` (`0x0e3ef0`, started by `CScan::OpenInterruptDetect` at `Register` line 83) computes a `StandbyReg` flag (lines 102 and 103) and never uses it. With this plist (`PollingButtonEvent = 1`, plist lines 393 to 394, skips the button branch at line 374; no `CoverSel`, no `LoaderInterruptReg`), its only register traffic is the holder eject check: while a holder is positioned, sleep 500 ms, then `IsLoaderReady` (lines 290 to 307), and 50 ms per loop (line 472).
- Other callers, from a search of the decompiled and disassembled files for `StandbyModeSel`, `StandbyModeControl` and `IsStandbyMode`: `StartScan` (`0x027c50`, `CScanApi__StartScan@00027c50.c` lines 254 and 478), `DoCalibration` (`0x034120`, line 25), `ExeDoCalibrate` (`0x046a80`, line 161) and `CAddOn::StartStaticScan` (`0x0030e0`, line 572) set the bit. `Unregister` (`0x01f470`) clears it (`CScanApi__Unregister@0001f470.c` lines 87, 190 and 195). No caller writes any other register as part of standby. The Windows engine has the same design (`../vendor-driver/windows.md`, "Question 5: standby").

So the engine knows one line, GPIO8, and one host-side event besides its own timer that re-asserts it: a ready film holder on GPIO3. A unit that leaves and rejoins the bus gets the full `Register`.

The capture agrees:

- Frames 127 to 138: the pulse at open.
- Frames 13473 to 13478 (278.65 s): read `0x31` → `0xbb`, write `0xbb`, a `StandbyModeControl(false)` with the bit already set, before the second preview *(inference: paired by shape, the capture is of the Windows engine)*.
- Frames 15479 to 15532 (301.9 s to 318.0 s): 27 reads of `0x31`, 0.61 s to 0.63 s apart (submit times in `work/captures/151/transfers.jsonl`), and no write. That fits the eject check's 500 ms plus the loop's 50 ms, with the holder ready (`0xbb`, bit 2 clear, one read per check) *(inference)*.
- Frames 15537 to 15542 (read `0xbb`, write `0x3b`) and 15873 to 15878 (read `0x3b`, write `0x3b`): the close clears bit 7.
- No other write to `0x31` occurs apart from the 12 blasts, which all write `0xfc`.

### 3. The smallest write set

The runs on the owner's unit so far (`../hardware/usb.md`, "Standby"):

| Run | Writes | Result |
|---|---|---|
| No host traffic, two wakes | none | left the bus 4 min 54 s and 4 min 55 s after the wake |
| `probe_readonly.py`, reads every 20 s | none | left 4 min 55 s after the wake |
| `keep_awake.py`, 1 s after the wake | `0x31 = 0xbc` (bit 7 already read high), `0x34 = 0x80` (`../hardware/probes/20261014T221655Z-keep-awake.jsonl`) | left 4 min 55 s after the wake |
| `vendor_open.py`, 11 s after the wake | frames 15 to 138 | still on the bus 7 min 20 s after the wake, 7 min 0 s after the open (`../hardware/probes/20261015T061444Z-vendor-open.jsonl`, `open_done` and the last `watch` record), and still answering 82 min after the wake with no polling in between (`../hardware/probes/20261015T073623Z-move-carrier.jsonl`) |

During the replayed pulse the unit read `0x31 = 0x3c` (frame 133 record of the same log), bit 7 low, so the pulse reached the pin.

Reading of these facts *(inference throughout this paragraph)*: GPIO8 reads high while its output is disabled (`0x31 = 0xbc` with `0x34 = 0x00` before any write), so the line idles high with no host, and a high level alone cannot tell the board's microcontroller (U11, `../hardware/board.md`) that a host is there. What the engine adds on this line is its low periods. The log line "scanner set into standby mode in 5 min", written right after the engine clears the bit, and the host limit of `StandbyOffTime` minus 5 minutes point to a 5 minute countdown in the unit, which is the 4 min 55 s seen after every wake. One model fits all four runs: the unit's countdown runs from a wake and from a falling edge of GPIO8, and a rising edge after a low period stops it. `keep_awake.py` never made the line low, `vendor_open.py` held it low for 13 ms. The open did not merely restart a 5 minute countdown either, since the unit stayed 7 minutes past the pulse.

**Run A, the proposed write set.** In order, each write followed by the link check (`c0 0c 008e` wIndex `0x20`) as after every write in the capture (`of120-capture-151.md`, safe probe set B1):

| Step | Request | Engine source | Capture | Basis |
|---|---|---|---|---|
| 1 | read `0x31`, write `0x31 = value \| 0x80` | patch `31.80` puts bit 7 into `0x31` ahead of `0x34` in the blast (`ReadKey`, `SoftwareResetScanner` line 58) | frame 21, `0x31` before `0x34` | code and capture. Writing the read value instead of `0xfc` keeps the input bits as read *(inference: they are inputs)*. Setting the level before the enable avoids a low glitch when the output turns on *(inference)* |
| 2 | write `0x34 = 0x80` | patch `34.80`, GPOE8 | frame 21 | code and capture |
| 3 | read `0x31`, write `value & 0x7f` | `StandbyModeSel(true)`, `Register` line 278 | frames 127 to 132 | code and capture |
| 4 | wait 10 ms | `_usleep(10000)`, line 279 | 13.3 ms from frame 129 to 135 | code and capture |
| 5 | read `0x31`, write `value \| 0x80` | `StandbyModeSel(false)`, line 280 | frames 133 to 138 | code and capture |
| 6 | afterwards, read `0x31` and set bit 7 when it reads clear | `SetStandbyOffTime` lines 78 to 86, every 5 s | | code. Nothing clears the bit during a watch, so a test run can leave this out *(inference)* |

Steps 1 and 2 are exactly what `keep_awake.py` sent, so run A differs from that failed run only in the pulse. It writes `0x31` and `0x34` only: no motor, lamp, clock or flash request. To change one thing at a time, keep `vendor_open.py`'s watch (link check and `0x101` every 20 s), and note the time from the wake and from the pulse. The write set is for the original board only: in the `-new1440` configuration GPIO8 is the holder sensor (`LoaderReadyReg = 0x31,0x80`, that plist's lines 148 to 149) and `StandbyReg` is switched off (`-StandbyReg`, line 731). The owner's board is the original revision (`../hardware/board.md`, "Date codes and the board revision", itself an inference there).

**If run A does not hold.** Add groups of `vendor_open.py`'s table in this order, one wake per run:

| Run | Adds | Table frames | Note |
|---|---|---|---|
| B | the whole GPIO area `0x30` to `0x3c` as in frame 21 (replacing steps 1 and 2), and `LoaderEjectSel` (`0x36` bit 1, then `0x33` bit 1) before the pulse | 21 (GPIO bytes), 113 to 124 | drives GPIO9 to 15, 18 to 24, 25 to 27, 29 to 31 and `GPO34` to the vendor's values at open. GPIO22 (`MotorReg = 0x33,0x20,0x00`, plist lines 167 to 168) goes low |
| C | the rest of the blast, `0x114`/`0x115`, clocks and DRAM refresh | 17 to 53 | writes `0x02 = 0x78` (`MTRPWR`), so `../hardware/board.md`, "Reassembly", applies |
| D | flash ID and infrared record, the `0x101` reads, lamp, AFE, the two one-byte reads: the full `vendor_open.py` | 15 to 138 | known to hold |

The first run that holds names the group, and the search continues by halves inside it: for B, `0x37`/`0x38` with `0x30` and `0x39` against `0x32`/`0x35` and `0x33`/`0x36`, for C the clocks with `0x114`/`0x115` against the blast. Seen from the full open, the drop order is the reverse: the reads, flash, lamp and AFE go first, then the clocks and the rest of the blast, then the GPIO area other than GPIO8. The pulse stays in every run. The order is a judgement of what could matter, with the reads dropped first because read-only polling did not hold the unit *(inference)*.

### 4. pyopticfilm

What it does at open on the 8200i SE:

- `Gl128.asic_boot` (`asic/gl128.py` lines 1246 to 1264): two 34-byte AHB writes at `0x000fff00` and `0x000fff01` (lines 157 to 160), the blast `INIT_REGS` (`device/gl128_common.py` lines 31 to 52), the memory layout, the AFE defaults and `GPO_REGS` (`0xa2` to `0xae`, lines 81 to 84). `Gl128.init` (`asic/gl128.py` lines 1266 to 1279) adds the slope and exposure tables. It sends no clock or flash request, no GPIO read-modify-write and no pulse. `update_home_sensor_gpio` is a no-op (lines 1398 to 1399).
- GPIO bytes in `INIT_REGS` (lines 38 to 40): `0x30 = 0x6f`, `0x31 = 0x00`, `0x32 = 0x22`, `0x33 = 0x04`, `0x34 = 0x80`, `0x35 = 0x2f`, `0x36 = 0x1c`, `0x37 = 0xc0`, `0x38 = 0x44`, `0x39 = 0x00`. The engine's 8200i SE configuration `ScanInfoVID_07B3_PID_1825.plist` gives the same bytes from its blob `0` with patches `32.20` and `35.20` (its lines 9 to 12), except `0x36`, which is `0x04` there (decoded with `python3 -I`). On the SE, GPIO8 is an output driven low.
- Standby: none. A search of `pyopticfilm/src` for `standby|keep.?alive|wake|power.?save` (case-insensitive) finds nothing. `Scanner.close` (`scanner.py` lines 122 to 131) switches the lamp off and stops the motor, nothing else. For the SE this matches the engine: `ScanInfoVID_07B3_PID_1825.plist` has neither `StandbyReg` nor `StandbyOffTime`, nor do the 8100 (`1824`) and 8300i SE (`181F`) files, so `StandbyModeSel` returns without I/O (`CAsic__StandbyModeSel@00061ac0.c` line 24) and no standby timer is armed (`CScanApi__InitStandbyModelOffTimeInfo@00022ee0.c` line 17).
- The SE's two 34-byte AHB writes have the size of `CAsic::CleanUserData` (`0x05b150`), which writes `0x22` bytes to `_UserAddr(0)` and `_UserAddr(1)`. The OpticFilm 120 plist turns that off with `DisableUserData = 1`, and its capture has no AHB write at open (`of120-capture-151.md`, "Differences from the 8200i SE boot") *(inference: matched by size and by the pair of calls only; the Open step checks it)*.

What an OpticFilm 120 model entry needs:

- GPIO values: `init_regs` with the GPIO area of part 1 (blob `0` plus patches, equal to frame 21).
- A standby hook in the open path after the blast: `LoaderEjectSel` (set `0x36` bit 1, then `0x33` bit 1), then the GPIO8 pulse (clear bit 7 by read-modify-write, 10 ms, set bit 7). `Gl128._update_bits` (`asic/gl128.py` lines 247 to 253) is the read-modify-write it needs. The model carries the line as data, `(0x31, 0x80)` from `StandbyReg`, and the existing models carry none, so the hook does nothing for them. If run A does not hold, the hook grows by the group the search finds.
- A close hook that clears `0x31` bit 7, as `Unregister` does, so that the unit falls back to its own standby.
- While open, setting bit 7 again when it reads clear, before each operation or on a timer, as `SetStandbyOffTime`, `StartScan` and `DoCalibration` do. Releasing the line after 10 idle minutes (`StandbyOffTime`) is host policy and optional *(inference)*.
- A caution for the later steps: pyopticfilm writes `0x33` as a depth register (`REG_DEPTH_A`, `asic/registers.py` line 90, written at `asic/gl128.py` lines 487 and 820) and `0x37` bit 2 as the infrared LED (`REG_IR`, `asic/registers.py` line 91, `asic/gl128.py` lines 1287 to 1292). On the OpticFilm 120 both are GPIO data registers with other keys on them. `0x33` carries `LoaderEjectSwitch` (GPIO18, plist lines 146 to 147), `MotorReg = 0x33,0x20,0x00` (GPIO22, lines 167 to 168), `SOLReg = 0x33,0x00,0x40` and the `33.40` patches of `Positive`, `Negative`, `PositiveIR` and `NegativeIR` (GPIO23, lines 603 to 604, 179, 292, 399, 506), `IRMask = 0x33,0x80,0x80` (GPIO24, lines 128 to 129) and `33.10` in `SPEED1` and `SPEED2` (GPIO21, lines 621 and 674). So the SE's `0x33` writes must not carry over to this model *(inference: the key names give the use)*.

pyopticfilm change this section implies: a standby line field on the GL128 model (unset for the 8200i SE, 8100 V2 and 8300i SE), an open hook after the blast that sends the eject-switch bits and the pulse when the field is set, a close hook that clears the bit, and a re-assert of the bit before operations. Nothing changes for the existing models. The hook's content waits for run A, so that it carries what the unit needs.
