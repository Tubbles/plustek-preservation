"""Map every function of a Mach-O x86_64 slice to the source file it was compiled from.

The macOS ScanApi binary keeps its STAB debugging entries: N_SO names each
compile unit, N_OSO its object file, N_SOL the included file the following
code came from (a header for the inline accessors, the .cpp otherwise), and
N_FUN with a name marks a function's start (the N_FUN with an empty name
after it is the end). Walking the entries in order attributes each function
to its compile unit and to the file that holds its body.

Usage:
    python3 -I tools/ghidra/macho_source_map.py work/re/slices/ScanApi.x86_64 work/re/source-map-x86_64.tsv

Output: a TSV with one line per function: address (hex), mangled symbol,
compile unit (the .cpp), the included file that holds the body (empty when
the body sits in the compile unit's own file before any include), and the
object file. A summary of functions per compile unit goes to stdout.
"""

import collections
import struct
import sys

MAGIC_64_LITTLE_ENDIAN = 0xFEEDFACF
LC_SYMTAB = 0x2
N_STAB_MASK = 0xE0
N_SO = 0x64
N_OSO = 0x66
N_SOL = 0x84
N_FUN = 0x24
NLIST_64_SIZE = 16


def symbol_table_command(data: bytes) -> tuple:
    """(symbol offset, symbol count, string table offset) from the LC_SYMTAB load command."""
    if struct.unpack_from("<I", data, 0)[0] != MAGIC_64_LITTLE_ENDIAN:
        raise ValueError("not a 64-bit little-endian Mach-O file")
    command_count = struct.unpack_from("<I", data, 16)[0]
    offset = 32
    for _ in range(command_count):
        command, size = struct.unpack_from("<II", data, offset)
        if command == LC_SYMTAB:
            symbol_offset, symbol_count, string_offset, _ = struct.unpack_from("<IIII", data, offset + 8)
            return symbol_offset, symbol_count, string_offset
        offset += size
    raise ValueError("no LC_SYMTAB load command")


def string_at(data: bytes, string_offset: int, index: int) -> str:
    end = data.index(b"\0", string_offset + index)
    return data[string_offset + index:end].decode("utf-8", "replace")


def stab_entries(data: bytes) -> list:
    """(n_type, name, n_value) for every STAB entry, in symbol table order."""
    symbol_offset, symbol_count, string_offset = symbol_table_command(data)
    entries = []
    for index in range(symbol_count):
        name_index, n_type, _, _, n_value = struct.unpack_from("<IBBHQ", data, symbol_offset + index * NLIST_64_SIZE)
        if n_type & N_STAB_MASK:
            entries.append((n_type, string_at(data, string_offset, name_index), n_value))
    return entries


def function_sources(entries: list) -> list:
    """(address, symbol, compile unit, included file, object file) for every function start."""
    compile_unit = included_file = object_file = ""
    functions = []
    for n_type, name, value in entries:
        if n_type == N_SO:
            if name == "" or name.endswith("/"):
                compile_unit = included_file = ""
            else:
                compile_unit = name
        elif n_type == N_OSO:
            object_file = name.rsplit("/", 1)[-1]
        elif n_type == N_SOL:
            included_file = name
        elif n_type == N_FUN and name:
            functions.append((value, name, compile_unit, included_file, object_file))
    return sorted(functions)


def write_table(path: str, functions: list) -> None:
    with open(path, "w") as output:
        output.write("address\tsymbol\tcompile_unit\tincluded_file\tobject_file\n")
        for address, symbol, compile_unit, included_file, object_file in functions:
            output.write(f"{address:08x}\t{symbol}\t{compile_unit}\t{included_file}\t{object_file}\n")


def main(arguments: list) -> int:
    if len(arguments) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(arguments[0], "rb") as handle:
        data = handle.read()
    functions = function_sources(stab_entries(data))
    write_table(arguments[1], functions)
    per_unit = collections.Counter(compile_unit for _, _, compile_unit, _, _ in functions)
    for compile_unit, count in sorted(per_unit.items()):
        print(f"{compile_unit:28} {count:5}")
    print(f"functions: {len(functions)}, compile units: {len(per_unit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
