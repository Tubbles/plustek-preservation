# Ghidra scripts for the Plustek engines

Static analysis of `PLK_A120.framework/Versions/A/ScanApi` from Plustek's macOS driver V3.1.0.0 (see `doc/vendor-driver/macos.md`) and of `Scanapi_x64.dll` from the Windows drivers V5.0.2.0 and V6.0.0.0 (see `doc/vendor-driver/windows.md`, "Disassembly"). Results are in `doc/protocol/serial-flash.md`, `doc/protocol/usb-requests.md`, `doc/protocol/gl128-registers.md`, the "Device discovery and model selection" section of `doc/vendor-driver/macos.md` and the "Disassembly" section of `doc/vendor-driver/windows.md`. Nothing here executes the vendor binaries.

Requirements: Ghidra 12.1.4 in `work/tools/ghidra_12.1.4_PUBLIC/` (headless launcher, default heap 2 GB) and a JDK 21; Python 3 for the `.py` helpers. All outputs go to `work/` (untracked). Run the commands from the repository root, one at a time.

## Scripts

| Script | Arguments | Output |
|---|---|---|
| `DecompileMatching.java` | output directory, regex on `Namespace::name` | one C file per matching function plus `INDEX.tsv` |
| `DisassembleMatching.java` | output directory, regex | one listing per matching function |
| `DumpFunctionTable.java` | output file | address, size, qualified name and prototype of every function |
| `FindScalars.java` | output file, hex values | every instruction with one of the values as an operand |
| `ListCallsWithConstants.java` | output file, regex on the callee | every call to a matching function with its constant arguments |
| `ListStringReferences.java` | output file | every defined string with each instruction that references it and the function containing that instruction |
| `DumpReferencesToFunctions.java` | output file | every reference to every function entry: callee, reference type, source address and the function containing the source (`-` for data such as vtables) |
| `ExtractAccessorFacts.java` | output file, comma separated class names | JSON lines with the calls, masks, shifts and shadow offsets of each register field accessor |
| `register_fields.py` | facts file, class, optional `--diff <class>` | Markdown field table, or the differences between two classes |
| `find_descriptor_bytes.py` | files | offsets of USB descriptor headers, VID/PID pairs and product strings |
| `find_code_references.py` | 64-bit PE file, target addresses | for each target, `E8`/`E9` relative calls and jumps to it at any byte offset of the code sections, and every 64-bit pointer or 32-bit RVA holding it, with the section |
| `macho_source_map.py` | Mach-O x86_64 slice, output file | TSV with every function's address, mangled symbol, compile unit, object file, linkage (`inline` for weak definitions with hidden visibility, which are the inline functions of the headers, `external`, `weak` for template instantiations, `local`) and the source files first seen in that function, from the STAB debugging entries (`N_SO`, `N_OSO`, `N_SOL`, `N_FUN`) and the symbol table. ld64 writes an `N_SOL` only where a file is first used, so it names the headers but does not attribute each function to a file |
| `macho_engine_tables.py` | Mach-O x86_64 slice, three output files | the class table (direct bases from the `__ZTI*` type information, every virtual base with its vtable slot and offset), the virtual functions of each class's own vtable, and the `CRegistry::m_prop` key table |
| `ApplyEngineTypes.java` | classes TSV, vtables TSV | changes the program (run it on a fresh import): `__thiscall` and the demangled parameter types for member functions (a hidden `this` is recognised by the argument registers the unoptimised code spills at entry, and with six or more integer parameters by the stack arguments the body reads; C2 and D2 of classes with virtual bases get the VTT parameter; the engine's own parameter types, which the demangler turns into a one byte placeholder without storage that makes the decompiler ignore the prototype, become empty enums of the same name as wide as their spill at entry, 8 bytes for `_SCANAPI_INPUT_SOURCE` and 4 for the others), `bool` for functions that end in `AND AL,0x1; MOVZX EAX,AL`, the decompiler's return type for the rest where it is at least 4 bytes wide, removes the `__TEXT` block at address 0 that holds the Mach-O header, and defines class structures: a `vptr` to a vtable structure with one named field per virtual base offset (Ghidra prints `ADJ(this->vptr)->CRegistryOffset`), `CRegister::m_reg` and its link lists, the `regBuf` and `regShadow` pointers of the GL classes, `CRegistry::propertyValues`, and `CRegistry::m_prop` typed as key table |
| `DumpClassMembers.java` | output file | the defined members of every class structure (class, offset, type, name, comment) |
| `reconstruct_engine.py` | `--decompiled` directory, `--output` root, input tables (defaults under `work/re/`) | the source tree `macos/Sources/`, `macos/FilmApi/`, `macos/Includes/` and `notes/architecture.md` (work item 0014), see the docstring for the rewrites |
| `test_reconstruct_engine.py` | none | unit tests of `reconstruct_engine.py` on captured snippets |

`ExtractAccessorFacts.java` and `ListCallsWithConstants.java` read the decompiler's P-code rather than its C text, because the C output of the untyped project (`work/ghidra`) prints small constants (register numbers, offsets) as fields of the Mach-O header, which Ghidra maps at address 0. The typed project (`work/ghidra-typed`, below) no longer has that block.

## Commands

```sh
mkdir -p work/re/slices work/ghidra
7z x -owork/re/slices work/extracted/mac-scanapi/ScanApi
mv 'work/re/slices/ScanApi~.x64' work/re/slices/ScanApi.x86_64
mv 'work/re/slices/ScanApi~.arm64' work/re/slices/ScanApi.arm64

GHIDRA=work/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless

# Import and auto-analyse the x86_64 slice (default analysers).
$GHIDRA work/ghidra ScanApi -import work/re/slices/ScanApi.x86_64

# Everything below opens the analysed program read-only.
$GHIDRA work/ghidra ScanApi -process ScanApi.x86_64 -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript DumpFunctionTable.java work/re/functions-x86_64.tsv \
  -postScript DecompileMatching.java work/re/decomp-x86_64 '.'

$GHIDRA work/ghidra ScanApi -process ScanApi.x86_64 -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript DisassembleMatching.java work/re/disasm-x86_64 '^(CIOUSB|CScanApi|CScan|CAsic|CGL128|CRegistry)::|^api' \
  -postScript FindScalars.java work/re/scalars-x86_64.tsv 26fe 8d 8a 8b 7b3 1406 5e3 103 1440 a0 2b 10 13

$GHIDRA work/ghidra ScanApi -process ScanApi.x86_64 -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript ListCallsWithConstants.java work/re/calls-control.tsv '^CIOUSB::Control(Read|Write)$' \
  -postScript ListCallsWithConstants.java work/re/calls-flash.tsv '^CIOUSB::(SFlash_|SPI_)' \
  -postScript ListCallsWithConstants.java work/re/calls-misc.tsv '^CIOUSB::(WriteUsbReg|MyWriteReg|HardwareResetScanner|SetupBulkLength|AHBWriteAddr|APB|InitInterrupt|CancelBulk|SysClock|AhbClock)'

$GHIDRA work/ghidra ScanApi -process ScanApi.x86_64 -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript ExtractAccessorFacts.java work/re/accessor-facts-x86_64.jsonl CGL128,CGL126,CGL125,CGL846

python3 -I tools/ghidra/register_fields.py work/re/accessor-facts-x86_64.jsonl CGL126
python3 -I tools/ghidra/register_fields.py work/re/accessor-facts-x86_64.jsonl CGL128
python3 -I tools/ghidra/register_fields.py work/re/accessor-facts-x86_64.jsonl CGL126 --diff CGL128

python3 -I tools/ghidra/find_descriptor_bytes.py work/re/slices/ScanApi.x86_64 work/re/slices/ScanApi.arm64

# Which compile unit each function came from and whether it is inline (the authors' file split, work item 0014).
python3 -I tools/ghidra/macho_source_map.py work/re/slices/ScanApi.x86_64 work/re/source-map-x86_64.tsv
```

## Reconstructed engine source

Work item `doc/work/0014-decompiled-code-cleanup.md`. The typed project is a second import, because `ApplyEngineTypes.java` changes the program and the scripts above expect the untyped one. On this laptop the import with the pass took about 5 minutes and the decompilation of all functions about 2 (2026-10-15).

```sh
GHIDRA=work/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless

python3 -I tools/ghidra/macho_source_map.py work/re/slices/ScanApi.x86_64 work/re/source-map-x86_64.tsv
python3 -I tools/ghidra/macho_engine_tables.py work/re/slices/ScanApi.x86_64 \
  work/re/classes-x86_64.tsv work/re/vtables-x86_64.tsv work/re/registry-keys-x86_64.tsv

mkdir -p work/ghidra-typed
$GHIDRA work/ghidra-typed ScanApi -import work/re/slices/ScanApi.x86_64 -scriptPath tools/ghidra \
  -postScript ApplyEngineTypes.java work/re/classes-x86_64.tsv work/re/vtables-x86_64.tsv

$GHIDRA work/ghidra-typed ScanApi -process ScanApi.x86_64 -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript DumpClassMembers.java work/re/members-x86_64.tsv \
  -postScript DumpFunctionTable.java work/re/functions-typed-x86_64.tsv \
  -postScript DecompileMatching.java work/re/decomp2-x86_64 '.'

python3 -I -B -m unittest discover -s tools/ghidra

# Into a scratch directory, then diff against the submodule and merge (engine/CLAUDE.md).
python3 -I tools/ghidra/reconstruct_engine.py --decompiled work/re/decomp2-x86_64 --output work/re/engine-scratch
diff -r work/re/engine-scratch/macos engine/macos
diff -r work/re/engine-scratch/notes engine/notes
```

## Windows engine

The engine comes out of the InstallShield cabinets of the driver package (`doc/vendor-driver/windows.md`). The V6.0.0.0 package is a RAR self-extractor, which `unrar x` unpacks (p7zip lacks the RAR5 method). The DLL has no symbols, so functions are traced by address and log string.

```sh
mkdir -p work/ghidra-win work/re-win
work/build/unshield/build/src/unshield -d work/extracted/plustek-V5020-cab64 \
  x 'work/extracted/plustek-V5020/OpticFilm 120_12L_V5.0.2.0/64bit/data1.hdr'

GHIDRA=work/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless
ENGINE=work/extracted/plustek-V5020-cab64/DRV_U_A31_x64/Scanapi_x64.dll

$GHIDRA work/ghidra-win ScanApiWin -import $ENGINE

$GHIDRA work/ghidra-win ScanApiWin -process Scanapi_x64.dll -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript DumpFunctionTable.java work/re-win/functions-x64.tsv \
  -postScript ListStringReferences.java work/re-win/string-refs-x64.tsv \
  -postScript DumpReferencesToFunctions.java work/re-win/references-x64.tsv \
  -postScript DecompileMatching.java work/re-win/decomp-x64 '.'

$GHIDRA work/ghidra-win ScanApiWin -process Scanapi_x64.dll -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript ListCallsWithConstants.java work/re-win/calls-control-x64.tsv '^FUN_1800f(d300|d1a0|ec10)$' \
  -postScript FindScalars.java work/re-win/scalars-x64.tsv 8b 8a 8c 8e 8f 7b3 1406 1440 5e3 103 26fe 30 a0 \
    80002024 8000201c 80002014 80002028 8000202c

# Back up "no caller" results (here: ChipErase, FlashSelfTest, ReadFromNVRAM, WriteIRScalingInfo).
python3 -I tools/ghidra/find_code_references.py $ENGINE 180102650 180103e50 180061130 180030200
```

The function names in `ListCallsWithConstants.java` patterns are Ghidra's default `FUN_<address>` names of this build: `0x1800fd300` is `ControlWrite`, `0x1800fd1a0` `ControlRead`, `0x1800fec10` `MyWriteReg`. The clients (`PkWiaDrv20_A31*.dll`, `WIAA3103.dll`, `ComScan.exe`) were imported into a second project and decompiled whole with `DecompileMatching.java ... '.'` to find which table slots they call.

Script names must not clash with Ghidra's bundled scripts (Ghidra already ships a `ListFunctions.java`), otherwise the headless analyser runs the bundled one.

## Notes on reading the output

- In the untyped output (`work/re/decomp-x86_64/`), Ghidra often gets the `this` parameter of these C++ methods wrong: functions it does not mark `__thiscall` show `this` as the first named parameter (for example `ReadReg(ushort param_1, ...)` where `param_1` is really `this`), and every call to such a method drops or shifts an argument (`CAsic::_RFHSET(this, true, 1)` in `CScanApi::SoftwareResetScanner` is really `_RFHSET(0xf, true, 0)`). The demangled signature in the comment above each function is authoritative. In the typed output (`work/re/decomp2-x86_64/`) every member function but the 8 static ones has the hidden `this` and the demangled parameter types (2026-10-15). Before the placeholder types were replaced, the decompiler ignored the prototype of the 36 functions (20 of them members) that take one of the engine's own types, such as `CScanApi::LampControl`.
- In the typed output, `ADJ(this->vptr)->CRegistryOffset` is the vtable slot that holds the offset of the virtual base `CRegistry` in the current object, so `(CRegistry *)((long)&this->vptr + ADJ(this->vptr)->CRegistryOffset)` is the `CRegistry` part of `this`. `&this->field_0x240 + ADJ(this->vptr)->CRegistryOffset` is byte 0x240 of that part (Ghidra uses the current class's one byte filler field for the offset), and `&this[n].field_0xK` is offset n times the structure's length plus K. `reconstruct_engine.py` rewrites these into `registry()` and `(undefined *)registry() + 0x240`.
- The register field accessors keep a 16-bit shadow per register at `register * 2`; see the docstring of `register_fields.py`. In the typed output that is `CRegister::m_reg`, reached from the GL classes through their `regBuf` and `regShadow` pointers.

## Limitations

- `ListCallsWithConstants.java` reports only arguments that are plain constants in the P-code. It does not fold the pointer arithmetic on the Mach-O header that the decompiler uses for small constants, so many register numbers show as `?`. `ExtractAccessorFacts.java` does fold them.
- `FindScalars.java` scans instruction operands only, not data sections or constants assembled at run time.
- `find_descriptor_bytes.py` finds a VID and PID only as an adjacent little-endian pair, not each value on its own.
- `DecompileMatching.java` does not shorten file names, so a very long C++ name can exceed the file system's name limit.
- `ApplyEngineTypes.java` leaves a function as Ghidra analysed it when it takes an aggregate by value (one function) or when it has six or more integer parameters and reads no more stack arguments than a static function would (none in this build, the log names any). The width of the engine's own parameter types comes from their spill at entry, and the enum that stands in for them is a guess at the kind of type: `_SCANAPI_INPUT_SOURCE` is 8 bytes, of which `apiLampControl` logs only the low 4, so whether it is an enum or a structure is open. Return types other than `bool` and the structors' `void` are the decompiler's inference, committed only when it is 4 bytes or wider and not `void` (a narrower or `void` inference broke the callers into `CONCAT62` and `extraout_EAX`); a function that ends by calling another one can get that callee's return type even where the source said `void`. 1009 of the 2709 functions, the stubs included, keep an undefined return type (2026-10-15). Parameters keep Ghidra's names (`param_1`).
- `reconstruct_engine.py` rewrites text, not P-code. It leaves an idiom as printed wherever its conditions do not hold: a parameter spill whose local has another type than the parameter (`uint local_14 = param_1` for an `int`), a virtual base offset kept in a local that also feeds other expressions (its stores stay, including those at the end of a block that no later read can see, since the script does not follow the paths out of a block), virtual calls whose slot has no name (pure virtual slots of `CIOUSB` and `CRegister`), and own virtual calls whose arguments Ghidra did not recover (`(*(code *)ADJ(this->vptr)->GetSevenSegment)()`).
