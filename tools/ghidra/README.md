# Ghidra scripts for the Plustek macOS engine

Static analysis of `PLK_A120.framework/Versions/A/ScanApi` from Plustek's macOS driver V3.1.0.0 (see `doc/vendor-driver/macos.md`). Results are in `doc/protocol/serial-flash.md`, `doc/protocol/usb-requests.md`, `doc/protocol/gl128-registers.md` and the "Device discovery and model selection" section of `doc/vendor-driver/macos.md`. Nothing here executes the vendor binary.

Requirements: Ghidra 12.1.4 in `work/tools/ghidra_12.1.4_PUBLIC/` (headless launcher, default heap 2 GB) and a JDK 21; Python 3 for the two `.py` helpers. All outputs go to `work/` (untracked). Run the commands from the repository root, one at a time.

## Scripts

| Script | Arguments | Output |
|---|---|---|
| `DecompileMatching.java` | output directory, regex on `Namespace::name` | one C file per matching function plus `INDEX.tsv` |
| `DisassembleMatching.java` | output directory, regex | one listing per matching function |
| `DumpFunctionTable.java` | output file | address, size, qualified name and prototype of every function |
| `FindScalars.java` | output file, hex values | every instruction with one of the values as an operand |
| `ListCallsWithConstants.java` | output file, regex on the callee | every call to a matching function with its constant arguments |
| `ExtractAccessorFacts.java` | output file, comma separated class names | JSON lines with the calls, masks, shifts and shadow offsets of each register field accessor |
| `register_fields.py` | facts file, class, optional `--diff <class>` | Markdown field table, or the differences between two classes |
| `find_descriptor_bytes.py` | files | offsets of USB descriptor headers, VID/PID pairs and product strings |

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

Script names must not clash with Ghidra's bundled scripts (Ghidra already ships a `ListFunctions.java`), otherwise the headless analyser runs the bundled one.

## Notes on reading the output

- Ghidra often gets the `this` parameter of these C++ methods wrong: functions it does not mark `__thiscall` show `this` as the first named parameter (for example `ReadReg(ushort param_1, ...)` where `param_1` is really `this`). The demangled signature in the comment above each function is authoritative.
- The register field accessors keep a 16-bit shadow per register at `register * 2`; see the docstring of `register_fields.py`.

## Limitations

- `ListCallsWithConstants.java` reports only arguments that are plain constants in the P-code. It does not fold the pointer arithmetic on the Mach-O header that the decompiler uses for small constants, so many register numbers show as `?`. `ExtractAccessorFacts.java` does fold them.
- `FindScalars.java` scans instruction operands only, not data sections or constants assembled at run time.
- `find_descriptor_bytes.py` finds a VID and PID only as an adjacent little-endian pair, not each value on its own.
- `DecompileMatching.java` does not shorten file names, so a very long C++ name can exceed the file system's name limit.
