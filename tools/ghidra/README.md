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

`ExtractAccessorFacts.java` and `ListCallsWithConstants.java` read the decompiler's P-code rather than its C text, because the C output prints small constants (register numbers, offsets) as fields of the Mach-O header, which Ghidra maps at address 0.

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

- Ghidra often gets the `this` parameter of these C++ methods wrong: functions it does not mark `__thiscall` show `this` as the first named parameter (for example `ReadReg(ushort param_1, ...)` where `param_1` is really `this`). The demangled signature in the comment above each function is authoritative.
- The register field accessors keep a 16-bit shadow per register at `register * 2`; see the docstring of `register_fields.py`.

## Limitations

- `ListCallsWithConstants.java` reports only arguments that are plain constants in the P-code. It does not fold the pointer arithmetic on the Mach-O header that the decompiler uses for small constants, so many register numbers show as `?`. `ExtractAccessorFacts.java` does fold them.
- `FindScalars.java` scans instruction operands only, not data sections or constants assembled at run time.
- `find_descriptor_bytes.py` finds a VID and PID only as an adjacent little-endian pair, not each value on its own.
- `DecompileMatching.java` does not shorten file names, so a very long C++ name can exceed the file system's name limit.
