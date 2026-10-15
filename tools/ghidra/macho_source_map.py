"""Map every function of a Mach-O x86_64 slice to the compile unit it was built from.

The macOS ScanApi binary keeps its STAB debugging entries (the debug map that
ld64 writes for dsymutil). N_SO names each compile unit and N_OSO its object
file. Each function sits between N_BNSYM and N_ENSYM: an N_FUN with its name
marks the start, an N_FUN with an empty name carries its size. An N_SOL inside
that bracket names a source file whose lines the function has, but ld64 emits
an N_SOL only the first time a file is seen (each file appears once in the
whole map), so N_SOL does not attribute each function to a file. It tells only
which function first used a header, which identifies the header's name.

Whether a function body sits in a header or in the .cpp comes from the regular
symbol table instead: an inline function (defined in a class body or declared
inline) is a weak definition with hidden visibility (N_PEXT with N_WEAK_DEF),
an ordinary definition is a strong external symbol, a static function is a
local symbol, and a template instantiation is a weak external one.

Usage:
    python3 -I tools/ghidra/macho_source_map.py work/re/slices/ScanApi.x86_64 work/re/source-map-x86_64.tsv

Output: a TSV with one line per function: address (hex), mangled symbol,
compile unit (the .cpp), object file, linkage (external, inline, weak or
local) and the files first seen in this function (comma separated, mostly
empty). A summary of functions per compile unit goes to stdout.
"""

import collections
import struct
import sys

MAGIC_64_LITTLE_ENDIAN = 0xFEEDFACF
LC_SYMTAB = 0x2
N_STAB_MASK = 0xE0
N_TYPE_MASK = 0x0E
N_SECT = 0x0E
N_PEXT = 0x10
N_EXT = 0x01
N_WEAK_DEF = 0x0080
N_SO = 0x64
N_OSO = 0x66
N_SOL = 0x84
N_FUN = 0x24
N_ENSYM = 0x4E
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


def symbol_entries(data: bytes) -> list:
    """(n_type, n_desc, name, n_value) for every symbol table entry, in order."""
    symbol_offset, symbol_count, string_offset = symbol_table_command(data)
    entries = []
    for index in range(symbol_count):
        name_index, n_type, _, n_desc, n_value = struct.unpack_from("<IBBHQ", data, symbol_offset + index * NLIST_64_SIZE)
        entries.append((n_type, n_desc, string_at(data, string_offset, name_index), n_value))
    return entries


def stab_entries(entries: list) -> list:
    """(n_type, name, n_value) for every STAB entry, in symbol table order."""
    return [(n_type, name, value) for n_type, _, name, value in entries if n_type & N_STAB_MASK]


def linkage_of(n_type: int, n_desc: int) -> str:
    """inline, weak, external or local, from a defined symbol's type and description bits."""
    if n_desc & N_WEAK_DEF:
        return "inline" if n_type & N_PEXT else "weak"
    return "external" if n_type & N_EXT else "local"


def linkage_by_address(entries: list) -> dict:
    """Linkage of every symbol defined in a section, keyed by (address, name)."""
    return {
        (value, name): linkage_of(n_type, n_desc)
        for n_type, n_desc, name, value in entries
        if not n_type & N_STAB_MASK and n_type & N_TYPE_MASK == N_SECT
    }


def function_sources(stabs: list) -> list:
    """[address, symbol, compile unit, object file, files first seen] for every function start."""
    compile_unit = object_file = ""
    current = None
    functions = []
    for n_type, name, value in stabs:
        if n_type == N_SO:
            compile_unit = name if name and not name.endswith("/") else ""
        elif n_type == N_OSO:
            object_file = name.rsplit("/", 1)[-1]
        elif n_type == N_FUN and name:
            current = [value, name, compile_unit, object_file, []]
            functions.append(current)
        elif n_type == N_SOL and current is not None:
            current[4].append(name)
        elif n_type == N_ENSYM:
            current = None
    return sorted(functions)


def write_table(path: str, functions: list, linkages: dict) -> None:
    with open(path, "w") as output:
        output.write("address\tsymbol\tcompile_unit\tobject_file\tlinkage\tfirst_seen_files\n")
        for address, symbol, compile_unit, object_file, first_seen in functions:
            linkage = linkages.get((address, symbol), "")
            output.write(f"{address:08x}\t{symbol}\t{compile_unit}\t{object_file}\t{linkage}\t{','.join(first_seen)}\n")


def main(arguments: list) -> int:
    if len(arguments) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(arguments[0], "rb") as handle:
        data = handle.read()
    entries = symbol_entries(data)
    functions = function_sources(stab_entries(entries))
    write_table(arguments[1], functions, linkage_by_address(entries))
    per_unit = collections.Counter(function[2] for function in functions)
    for compile_unit, count in sorted(per_unit.items()):
        print(f"{compile_unit:28} {count:5}")
    print(f"functions: {len(functions)}, compile units: {len(per_unit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
