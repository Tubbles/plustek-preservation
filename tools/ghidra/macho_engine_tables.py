"""Extract the C++ class tables of the macOS engine from its Mach-O x86_64 slice.

Three tables, all read from the binary's data (Itanium C++ ABI layouts):

- Classes: for every class with type information (`__ZTI<class>`), its direct
  bases from the type information record (`__si_class_type_info` or
  `__vmi_class_type_info`, told apart by the symbol its first word is bound
  to), and every virtual base, direct or indirect, with the vtable slot that
  holds its offset (the slot read by `this + *(long *)(*(long *)this + slot)`
  in the decompiled code) and its offset in a complete object. The slots come
  from the ABI's ordering (virtual bases in depth first, left to right,
  preorder of the inheritance graph, the first at -0x18); the script checks
  them against the slots the type information gives for direct virtual bases
  and against the number of offsets in the class's own vtable.
- Vtables: the virtual function entries of each class's own vtable, from the
  address point (after the type information pointer) on, with the target
  symbol, or the bound symbol for entries the dynamic linker fills in (such as
  `___cxa_pure_virtual`).
- Registry keys: the property table `CRegistry::m_prop` (16 byte entries: key
  string, value count, value index filled in at run time). The decompiled
  `CRegistry::<Key>` accessors read the index field of their entry.

Usage:
    python3 -I tools/ghidra/macho_engine_tables.py work/re/slices/ScanApi.x86_64 \\
        work/re/classes-x86_64.tsv work/re/vtables-x86_64.tsv work/re/registry-keys-x86_64.tsv
"""

import dataclasses
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho_source_map  # noqa: E402  (sibling module, path set above)

LC_SEGMENT_64 = 0x19
LC_DYLD_INFO_ONLY = 0x80000022
WORD_SIZE = 8
ADDRESS_MASK = (1 << 64) - 1
# Bind opcodes, named as in mach-o/loader.h. Opcodes not listed here carry
# their operand in the immediate and change nothing the tables need.
BIND_OPCODE_MASK = 0xF0
BIND_IMMEDIATE_MASK = 0x0F
BIND_OPCODE_DONE = 0x00
BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB = 0x20
BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_OPCODE_SET_ADDEND_SLEB = 0x60
BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_OPCODE_ADD_ADDR_ULEB = 0x80
BIND_OPCODE_DO_BIND = 0x90
BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB = 0xA0
BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED = 0xB0
BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB = 0xC0
FIRST_VIRTUAL_BASE_SLOT = -0x18
SI_CLASS_TYPE_INFO = "__ZTVN10__cxxabiv120__si_class_type_infoE"
VMI_CLASS_TYPE_INFO = "__ZTVN10__cxxabiv121__vmi_class_type_infoE"
VIRTUAL_BASE_FLAG = 0x1
REGISTRY_TABLE_SYMBOL = "__ZN9CRegistry6m_propE"
REGISTRY_ENTRY_SIZE = 16
REGISTRY_INDEX_FIELD = 12


def word_at(data: bytes, address: int) -> int:
    """Unsigned 64-bit word at an address (the slice maps file offset = address)."""
    return struct.unpack_from("<Q", data, address)[0]


def signed_word(value: int) -> int:
    return value - (1 << 64) if value & (1 << 63) else value


def load_commands(data: bytes) -> list:
    """(command, offset of the command) for every load command."""
    count = struct.unpack_from("<I", data, 16)[0]
    commands, offset = [], 32
    for _ in range(count):
        command, size = struct.unpack_from("<II", data, offset)
        commands.append((command, offset))
        offset += size
    return commands


def segment_addresses(data: bytes) -> list:
    """Virtual address of every segment, in load command order (the bind opcodes' segment index)."""
    return [struct.unpack_from("<Q", data, offset + 24)[0] for command, offset in load_commands(data) if command == LC_SEGMENT_64]


def read_uleb(data: bytes, position: int) -> tuple:
    value = shift = 0
    while True:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, position


def bind_opcodes_range(data: bytes) -> tuple:
    """(offset, size) of the non-lazy bind opcodes from LC_DYLD_INFO_ONLY."""
    for command, offset in load_commands(data):
        if command == LC_DYLD_INFO_ONLY:
            return struct.unpack_from("<II", data, offset + 16)
    return 0, 0


@dataclasses.dataclass
class BindState:
    """The registers of the bind opcode interpreter that matter for the tables."""

    position: int
    address: int = 0
    symbol: str = ""


def set_bind_state(data: bytes, segments: list, state: BindState, opcode: int, immediate: int) -> None:
    """Apply an opcode that changes the state without binding (the others read nothing here)."""
    if opcode in (BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB, BIND_OPCODE_SET_ADDEND_SLEB):
        _, state.position = read_uleb(data, state.position)  # skips a SLEB too, the value is not needed
    elif opcode == BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM:
        end = data.index(b"\0", state.position)
        state.symbol, state.position = data[state.position:end].decode("utf-8", "replace"), end + 1
    elif opcode == BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB:
        offset, state.position = read_uleb(data, state.position)
        state.address = segments[immediate] + offset
    elif opcode == BIND_OPCODE_ADD_ADDR_ULEB:
        offset, state.position = read_uleb(data, state.position)
        state.address = (state.address + offset) & ADDRESS_MASK


def bind_repetitions(data: bytes, state: BindState, opcode: int, immediate: int) -> tuple:
    """(count, address step) of the binds an opcode does, after reading its operands; (0, 0) for the others."""
    if opcode == BIND_OPCODE_DO_BIND:
        return 1, WORD_SIZE
    if opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB:
        offset, state.position = read_uleb(data, state.position)
        return 1, WORD_SIZE + offset
    if opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED:
        return 1, WORD_SIZE + immediate * WORD_SIZE
    if opcode == BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB:
        count, state.position = read_uleb(data, state.position)
        skip, state.position = read_uleb(data, state.position)
        return count, WORD_SIZE + skip
    return 0, 0


def step_bind_opcode(data: bytes, segments: list, state: BindState, bindings: dict) -> bool:
    """Run the opcode at the state's position and record its binds; False at BIND_OPCODE_DONE."""
    opcode, immediate = data[state.position] & BIND_OPCODE_MASK, data[state.position] & BIND_IMMEDIATE_MASK
    state.position += 1
    if opcode == BIND_OPCODE_DONE:
        return False
    set_bind_state(data, segments, state, opcode, immediate)
    count, step = bind_repetitions(data, state, opcode, immediate)
    for _ in range(count):
        bindings[state.address] = state.symbol
        state.address = (state.address + step) & ADDRESS_MASK
    return True


def bound_symbols(data: bytes) -> dict:
    """Address to symbol name for every pointer the dynamic linker binds (non-lazy binds)."""
    start, size = bind_opcodes_range(data)
    segments = segment_addresses(data)
    state, bindings = BindState(position=start), {}
    while state.position < start + size:
        if not step_bind_opcode(data, segments, state, bindings):
            break
    return bindings


def defined_symbols(data: bytes) -> dict:
    """Name to address of every symbol defined in a section."""
    entries = macho_source_map.symbol_entries(data)
    return {
        name: value
        for n_type, _, name, value in entries
        if not n_type & macho_source_map.N_STAB_MASK and n_type & macho_source_map.N_TYPE_MASK == macho_source_map.N_SECT
    }


def simple_class_name(mangled: str, prefix: str):
    """'CAsic' from '__ZTI5CAsic' with prefix '__ZTI'; None for nested or template names."""
    rest = mangled[len(prefix):]
    digits = len(rest) - len(rest.lstrip("0123456789"))
    if digits == 0:
        return None
    length = int(rest[:digits])
    name = rest[digits:]
    return name if len(name) == length else None


def typeinfo_addresses(symbols: dict) -> dict:
    """Class name to the address of its type information record."""
    classes = {}
    for name, address in symbols.items():
        if name.startswith("__ZTI"):
            class_name = simple_class_name(name, "__ZTI")
            if class_name:
                classes[class_name] = address
    return classes


def direct_bases(data: bytes, address: int, kind: str, class_at: dict) -> list:
    """[(base class, is virtual, offset or vtable slot)] from one type information record."""
    if kind == SI_CLASS_TYPE_INFO:
        return [(class_at[word_at(data, address + 16)], False, 0)]
    if kind != VMI_CLASS_TYPE_INFO:
        return []
    count = word_at(data, address + 16) >> 32
    bases = []
    for index in range(count):
        entry = address + 24 + index * 16
        offset_flags = signed_word(word_at(data, entry + 8))
        bases.append((class_at[word_at(data, entry)], bool(offset_flags & VIRTUAL_BASE_FLAG), offset_flags >> 8))
    return bases


def virtual_bases_in_order(class_name: str, bases_of: dict) -> list:
    """Every virtual base of a class, direct or indirect, in the ABI's inheritance graph order."""
    order = []

    def visit(name):
        for base, is_virtual, _ in bases_of.get(name, []):
            if is_virtual and base in order:
                continue
            if is_virtual:
                order.append(base)
            visit(base)

    visit(class_name)
    return order


def vtable_address_point(data: bytes, vtable: int, typeinfo: int) -> int:
    """Address just past the type information pointer of a class's primary vtable."""
    address = vtable
    while word_at(data, address) != typeinfo:
        address += WORD_SIZE
    return address + WORD_SIZE


def virtual_base_offsets(data: bytes, vtable: int, address_point: int) -> list:
    """Offsets stored in the primary vtable's virtual base slots, from slot -0x18 outward."""
    first_slot = address_point + FIRST_VIRTUAL_BASE_SLOT
    return [signed_word(word_at(data, slot)) for slot in range(first_slot, vtable - 1, -WORD_SIZE)]


def virtual_functions(data: bytes, address_point: int, function_at: dict, bindings: dict) -> list:
    """[(slot, target address, symbol)] for the entries of a primary vtable."""
    entries, address = [], address_point
    while True:
        target = word_at(data, address)
        if target in function_at:
            entries.append((address - address_point, target, function_at[target]))
        elif target == 0 and address in bindings:
            entries.append((address - address_point, 0, bindings[address]))
        else:
            return entries
        address += WORD_SIZE


def class_rows(class_name: str, bases: list, virtual_order: list, offsets: list) -> list:
    """TSV rows (class, base, relation, vtable slot, offset) for one class."""
    rows = []
    direct_virtual = {base for base, is_virtual, _ in bases if is_virtual}
    for base, is_virtual, offset in bases:
        if not is_virtual:
            rows.append((class_name, base, "base", "", str(offset)))
    for index, base in enumerate(virtual_order):
        relation = "virtual base" if base in direct_virtual else "indirect virtual base"
        slot = FIRST_VIRTUAL_BASE_SLOT - index * WORD_SIZE
        offset = str(offsets[index]) if index < len(offsets) else ""
        rows.append((class_name, base, relation, f"-0x{-slot:x}", offset))
    return rows or [(class_name, "", "no base", "", "")]


def slot_mismatches(class_name: str, bases: list, virtual_order: list, offsets: list) -> list:
    """Messages where the computed virtual base slots disagree with the binary."""
    problems = []
    if len(offsets) != len(virtual_order):
        problems.append(f"{class_name}: {len(offsets)} virtual base offsets in the vtable, {len(virtual_order)} virtual bases")
    for base, is_virtual, slot in bases:
        if is_virtual and FIRST_VIRTUAL_BASE_SLOT - virtual_order.index(base) * WORD_SIZE != slot:
            problems.append(f"{class_name}: {base} at slot {slot}, computed otherwise")
    return problems


def registry_keys(data: bytes, symbols: dict) -> list:
    """[(entry index, address of its index field, key, value count)] of CRegistry::m_prop."""
    start = symbols[REGISTRY_TABLE_SYMBOL]
    following = min(address for address in symbols.values() if address > start)
    keys = []
    for entry in range(start, following, REGISTRY_ENTRY_SIZE):
        key_address, count = struct.unpack_from("<QI", data, entry)
        end = data.index(b"\0", key_address)
        keys.append(((entry - start) // REGISTRY_ENTRY_SIZE, entry + REGISTRY_INDEX_FIELD, data[key_address:end].decode("latin-1"), count))
    return keys


def write_rows(path: str, header: str, rows: list) -> None:
    with open(path, "w") as output:
        output.write(header + "\n")
        for row in rows:
            output.write("\t".join(str(column) for column in row) + "\n")


def main(arguments: list) -> int:
    if len(arguments) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    with open(arguments[0], "rb") as handle:
        data = handle.read()
    symbols = defined_symbols(data)
    bindings = bound_symbols(data)
    typeinfos = typeinfo_addresses(symbols)
    class_at = {address: name for name, address in typeinfos.items()}
    function_at = {address: name for name, address in symbols.items() if not name.startswith("__ZT")}
    bases_of = {name: direct_bases(data, address, bindings.get(address, ""), class_at) for name, address in typeinfos.items()}
    class_table, vtable_table, problems = [], [], []
    for class_name in sorted(typeinfos):
        vtable = symbols.get(f"__ZTV{len(class_name)}{class_name}")
        virtual_order = virtual_bases_in_order(class_name, bases_of)
        offsets, functions = [], []
        if vtable is not None:
            address_point = vtable_address_point(data, vtable, typeinfos[class_name])
            offsets = virtual_base_offsets(data, vtable, address_point)
            functions = virtual_functions(data, address_point, function_at, bindings)
        class_table += class_rows(class_name, bases_of[class_name], virtual_order, offsets)
        vtable_table += [(class_name, f"0x{slot:x}", f"{target:08x}", symbol) for slot, target, symbol in functions]
        problems += slot_mismatches(class_name, bases_of[class_name], virtual_order, offsets)
    write_rows(arguments[1], "class\tbase\trelation\tvtable_slot\toffset", class_table)
    write_rows(arguments[2], "class\tslot\taddress\tsymbol", vtable_table)
    write_rows(arguments[3], "entry\tindex_address\tkey\tvalue_count", [(entry, f"{address:08x}", key, count) for entry, address, key, count in registry_keys(data, symbols)])
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"classes: {len(typeinfos)}, vtable entries: {len(vtable_table)}, mismatches: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
