"""Turn the decompiled macOS engine into a C++ source tree in the authors' file split.

Inputs (all regenerable, see tools/ghidra/README.md):
- the source map from macho_source_map.py: compile unit and linkage of every
  function. An inline function (weak definition with hidden visibility) goes
  into its class's header, every other function into its compile unit's .cpp
  (Sources/ or FilmApi/, as the binary's debug map names them). Functions
  without a map entry (stubs, externals) are listed in Sources/Unmapped.cpp.
- the class, vtable and registry key tables from macho_engine_tables.py, and
  the class members that ApplyEngineTypes.java defined.
- a directory written by DecompileMatching.java after ApplyEngineTypes.java.
- doc/vendor-driver/macos.md for one line per class in the architecture note.

Each function keeps "// at 0x<address>" and its demangled signature. The
Ghidra idioms are rewritten only where a textual rewrite is provably the same
code: virtual base casts become helper calls (registry(), usb(), ...), calls
through them become member calls, a parameter spilled to a local of the same
type that neither side changes is folded back onto the parameter, and locals
that nothing reads are dropped. Everything else stays as Ghidra printed it.

Usage (from the repository root):
    python3 -I tools/ghidra/reconstruct_engine.py --decompiled work/re/decomp2-x86_64 --output engine
"""

import argparse
import collections
import csv
import dataclasses
import os
import re
import sys

# ---- data ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class MapEntry:
    address: int
    symbol: str
    compile_unit: str
    object_file: str
    linkage: str
    first_seen_files: tuple


@dataclasses.dataclass(frozen=True)
class Function:
    address: int
    qualified_name: str
    demangled: str
    definition: str


@dataclasses.dataclass(frozen=True)
class BaseRelation:
    class_name: str
    base: str
    relation: str
    vtable_slot: int
    offset: int


@dataclasses.dataclass(frozen=True)
class Member:
    class_name: str
    offset: int
    type_name: str
    name: str
    comment: str


@dataclasses.dataclass(frozen=True)
class Placement:
    path: str
    inline: bool


UNMAPPED_PATH = "Sources/Unmapped.cpp"
GENERATOR = "tools/ghidra/reconstruct_engine.py"

# ---- reading --------------------------------------------------------------------


def read_tsv(path: str) -> list:
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))


def parse_map_rows(rows: list) -> dict:
    return {
        int(row["address"], 16): MapEntry(
            int(row["address"], 16), row["symbol"], row["compile_unit"], row["object_file"], row["linkage"],
            tuple(name for name in row["first_seen_files"].split(",") if name),
        )
        for row in rows
    }


def parse_class_rows(rows: list) -> list:
    return [
        BaseRelation(
            row["class"], row["base"], row["relation"],
            -int(row["vtable_slot"][3:], 16) if row["vtable_slot"] else None,
            int(row["offset"]) if row["offset"] else None,
        )
        for row in rows
    ]


def parse_member_rows(rows: list) -> list:
    return [Member(row["class"], int(row["offset"], 16), row["type"], row["name"], row["comment"]) for row in rows]


def structure_lengths(rows: list) -> dict:
    """{class: length of its Ghidra structure} from the member dump."""
    return {row["class"]: int(row["structure_length"], 16) for row in rows}


def vtable_slot_names(rows: list, function_names: dict) -> dict:
    """{(class, slot): method name} for every vtable entry with a known target."""
    names = {}
    for row in rows:
        name = function_names.get(int(row["address"], 16))
        if name:
            names[(row["class"], int(row["slot"], 16))] = name.split("::")[-1]
    return names


def registry_keys_by_entry(rows: list) -> dict:
    return {int(row["entry"]): row["key"] for row in rows}


def parse_decompiled_text(text: str) -> tuple:
    """(demangled signature, definition text) of one DecompileMatching.java file.

    The definition head is the run of lines before the opening brace, which
    Ghidra wraps over up to four lines ("bool __thiscall" on a line of its
    own, the parameters continued below); it is joined into one line.
    """
    plate = re.search(r"^/\* (.*?) \*/\s*$", text, re.MULTILINE)
    demangled = plate.group(1) if plate else ""
    lines = text.split("\n")
    if "{" not in lines:
        return demangled, text.strip("\n")
    end = head_end(lines, lines.index("{"))
    start = head_start(lines, end)
    return demangled, "\n".join([join_head(lines[start:end])] + lines[end:]).strip("\n")


def head_end(lines: list, brace: int) -> int:
    """Index just past the definition head: the blank line before the brace, or the brace."""
    return brace - 1 if brace > 0 and lines[brace - 1] == "" else brace


def head_start(lines: list, end: int) -> int:
    """First line of the head: the run of non-empty, non-comment lines before end."""
    start = end
    while start > 0 and lines[start - 1] and not lines[start - 1].startswith(("//", "/*")):
        start -= 1
    return start


def join_head(lines: list) -> str:
    head = lines[0] if lines else ""
    for line in lines[1:]:
        head += join_separator(head, line.strip()) + line.strip()
    return head


def read_decompiled(directory: str) -> list:
    functions = []
    for row in read_tsv_without_header(os.path.join(directory, "INDEX.tsv"), ("address", "name", "file")):
        with open(os.path.join(directory, row["file"])) as handle:
            demangled, definition = parse_decompiled_text(handle.read())
        functions.append(Function(int(row["address"], 16), row["name"], demangled, definition))
    return sorted(functions, key=lambda function: function.address)


def read_tsv_without_header(path: str, columns: tuple) -> list:
    with open(path, newline="") as handle:
        return [dict(zip(columns, line.rstrip("\n").split("\t"))) for line in handle if line.strip()]


def class_purposes(markdown: str, class_names: set) -> dict:
    """First sentence after "- `CName` (also `COther`):" in the class list of doc/vendor-driver/macos.md."""
    purposes = {}
    for match in re.finditer(r"^- (`C\w+`[^:\n]*): (.+)$", markdown, re.MULTILINE):
        for name in re.findall(r"`(C\w+)`", match.group(1)):
            if name in class_names and name not in purposes:
                purposes[name] = first_sentence(match.group(2))
    return purposes


def first_sentence(text: str) -> str:
    match = re.match(r"(.+?\.)(\s|$)", text)
    return match.group(1) if match else text


# ---- placement ------------------------------------------------------------------


def class_of(qualified_name: str):
    """'CAsic' for 'CAsic::MotorSel', None for a free function."""
    parts = qualified_name.split("::")
    return parts[0] if len(parts) > 1 and parts[0].startswith("C") else None


def unit_directories(entries: dict) -> dict:
    """{'Asic.cpp': 'Sources', 'MAPTOOLS.cpp': 'FilmApi'} from the files first seen per unit."""
    directories = {}
    for entry in entries.values():
        for name in entry.first_seen_files:
            if name.endswith("/" + entry.compile_unit):
                directories[entry.compile_unit] = name.split("/")[0]
    return directories


def header_candidates(entries: dict, names_by_address: dict) -> dict:
    """{'CIOUSB': {'Includes/Usb.h', 'Includes/USB.h'}}: the headers first used by each class's functions."""
    candidates = collections.defaultdict(set)
    for entry in entries.values():
        class_name = class_of(names_by_address.get(entry.address, ""))
        for name in entry.first_seen_files:
            if class_name and name.startswith("Includes/"):
                candidates[class_name].add(name)
    return candidates


def class_headers(entries: dict, names_by_address: dict) -> dict:
    """{'CAsic': 'Includes/Asic.h'} from the function that first used each header."""
    candidates = header_candidates(entries, names_by_address)
    return {class_name: preferred_header(class_name, names) for class_name, names in candidates.items()}


def other_header_spellings(entries: dict, names_by_address: dict) -> dict:
    """{'Includes/USB.h': ['Includes/Usb.h']}: the candidates class_headers did not pick, by the one it picked."""
    spellings = {}
    for class_name, names in header_candidates(entries, names_by_address).items():
        others = sorted(names - {preferred_header(class_name, names)})
        if others:
            spellings[preferred_header(class_name, names)] = others
    return spellings


def preferred_header(class_name: str, names: set) -> str:
    """The spelling whose stem matches the class name exactly (USB.h over Usb.h for CIOUSB)."""
    exact = [name for name in names if class_name.endswith(header_stem(name))]
    return sorted(exact or names)[0]


def header_stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def default_header(class_name: str) -> str:
    return f"Includes/{class_name[1:]}.h"


def place_function(function: Function, entry, directories: dict, headers: dict) -> Placement:
    if entry is None:
        return Placement(UNMAPPED_PATH, False)
    class_name = class_of(function.qualified_name)
    if entry.linkage == "inline" and class_name:
        return Placement(headers.get(class_name, default_header(class_name)), True)
    return Placement(f"{directories.get(entry.compile_unit, 'Sources')}/{entry.compile_unit}", False)


# ---- names ----------------------------------------------------------------------

SPECIAL_HELPER_NAMES = {"CIOUSB": "usb", "CRegister": "registers"}


def helper_name(class_name: str) -> str:
    """Accessor name for a virtual base: registry() for CRegistry, gl846() for CGL846."""
    if class_name in SPECIAL_HELPER_NAMES:
        return SPECIAL_HELPER_NAMES[class_name]
    stem = class_name[1:]
    if len(stem) > 1 and stem[1].isupper():
        return stem.lower()
    return stem[0].lower() + stem[1:]


# ---- text rewrites --------------------------------------------------------------

IDENTIFIER_END = re.compile(r"\w$")
IDENTIFIER_START = re.compile(r"^\w")
OPERATOR_END = re.compile(r"[-+*/%&|^=<>?:]$")


def join_wrapped_lines(text: str) -> str:
    """Join the lines Ghidra wraps at 100 columns back into one line per statement."""
    joined = []
    for line in text.split("\n"):
        if joined and continues_statement(joined[-1]):
            joined[-1] = joined[-1] + join_separator(joined[-1], line.strip()) + line.strip()
        else:
            joined.append(line)
    return "\n".join(joined)


def join_separator(previous: str, following: str) -> str:
    """A space between two words or after an operator, nothing after '(' or ','."""
    if previous.endswith(("->", "(", "[")):
        return ""
    if OPERATOR_END.search(previous) or (IDENTIFIER_END.search(previous) and IDENTIFIER_START.search(following)):
        return " "
    return ""


def continues_statement(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("/*", "//", "#")) or stripped.endswith(("*/", ":")):
        return False
    if re.match(r"^\w[\w\s\*&:<>,~]*\(.*\)$", stripped) and line == stripped:
        return False
    return not stripped.endswith((";", "{", "}"))


def normalize_adjusted_access(text: str) -> str:
    """ADJ(p).field and ADJ(p)->field print the same vtable slot; use the arrow form."""
    return re.sub(r"ADJ\(([^()]*)\)\.(\w+)", r"ADJ(\1)->\2", text)


THIS_ADDRESS = r"\(long\)&this->vptr\s*\+\s*"
VIRTUAL_BASE_SLOT = r"ADJ\(this->vptr\)->(\w+)Offset"
# An expression that stands as a whole argument or parenthesised operand.
ENCLOSED = r"(?<=[(,]){}(?=[),])"
THIS_FIELD = r"&this(?:\[(0x[0-9a-f]+|\d+)\])?(?:->|\.)field_0x([0-9a-f]+)"


def rewrite_virtual_base_casts(text: str, virtual_bases: set) -> str:
    """(B *)((long)&this->vptr + ADJ(this->vptr)->BOffset) and (B *)((long)b()) become b()."""

    def replace(match):
        cast, base = match.group(1), match.group(2)
        if base not in virtual_bases:
            return match.group(0)
        helper = f"{helper_name(base)}()"
        return helper if cast == base else f"({cast} *){helper}"

    text = re.sub(r"\((\w+) \*\)\(" + THIS_ADDRESS + VIRTUAL_BASE_SLOT + r"\)", replace, text)
    by_helper = {helper_name(base): base for base in virtual_bases}

    def replace_long(match):
        cast, helper = match.group(1), match.group(2)
        if helper not in by_helper:
            return match.group(0)
        return f"{helper}()" if cast == by_helper[helper] else f"({cast} *){helper}()"

    return re.sub(r"\((\w+) \*\)\(\(long\)(\w+)\(\)\)", replace_long, text)


def rewrite_virtual_base_addresses(text: str, virtual_bases: set) -> str:
    """The uncast address '(long)&this->vptr + ADJ(this->vptr)->BOffset' becomes '(long)b()'."""

    def replace(match):
        base = match.group(1)
        return f"(long){helper_name(base)}()" if base in virtual_bases else match.group(0)

    return re.sub(ENCLOSED.format(THIS_ADDRESS + VIRTUAL_BASE_SLOT), replace, text)


def field_offset(index: str, field: str, structure_length: int):
    """Byte offset of '&this[index].field_0x<field>', None when the length is unknown."""
    if index is None:
        return int(field, 16)
    return None if structure_length is None else int(index, 0) * structure_length + int(field, 16)


def rewrite_virtual_base_fields(text: str, virtual_bases: set, structure_length) -> str:
    """'&this->field_0xK + ADJ(this->vptr)->BOffset' (byte arithmetic on Ghidra's filler) is b() + K.

    Ghidra prints an access into a virtual base as the address of the current
    class's one byte filler field at the same offset plus the base's offset,
    and as '&this[n].field_0xK' past the end of the structure.
    """

    def address(match, index_form):
        index, field, base = match.group(1), match.group(2), match.group(3)
        offset = field_offset(index, field, structure_length)
        if base not in virtual_bases or offset is None:
            return match.group(0)
        pointer = f"(undefined *){helper_name(base)}()"
        return f"({pointer})[0x{offset:x}]" if index_form else f"{pointer} + 0x{offset:x}"

    text = re.sub(r"\(" + THIS_FIELD + r"\)\[" + VIRTUAL_BASE_SLOT + r"\]", lambda match: address(match, True), text)
    return re.sub(THIS_FIELD + r"\s*\+\s*" + VIRTUAL_BASE_SLOT, lambda match: address(match, False), text)


def fold_virtual_base_temporaries(text: str, virtual_bases: set) -> str:
    """Locals that hold a virtual base offset and feed '(long)&this->vptr + t' become the helper.

    The offset in a vtable slot is fixed for the object. A local that only
    ever holds one base's offset is that helper wherever it is used. A local
    reused for several bases is folded only in the straight-line statements
    that follow each assignment in the same block, where no other assignment
    can reach. Assignments left without a use are dropped (reading a vtable
    slot has no side effect).
    """
    candidates = set(re.findall(r"^\s*(\w+) = " + VIRTUAL_BASE_SLOT + ";$", text, re.MULTILINE))
    for temporary in {name for name, _ in candidates}:
        bases = {base for name, base in candidates if name == temporary}
        assignments = set(re.findall(rf"^\s*{temporary} = (.*);$", text, re.MULTILINE))
        if len(bases) == 1 and bases <= virtual_bases and assignments == {f"ADJ(this->vptr)->{next(iter(bases))}Offset"}:
            text = substitute_temporary(text, temporary, next(iter(bases)))
        else:
            text = fold_in_straight_lines(text, temporary, virtual_bases)
        text = drop_dead_temporary_stores(text, temporary)
        text = drop_unused_temporary(text, temporary)
    return text


def indentation_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def drop_dead_temporary_stores(text: str, temporary: str) -> str:
    """Drop 't = ADJ(this->vptr)->BOffset;' when the same block stores t again before any read.

    Between the two stores there must be no read of t, no exit from the
    block (a line indented less), no label and no jump (goto, break,
    continue), so that no path from the first store reads its value.
    """
    lines = text.split("\n")
    store = re.compile(rf"^\s*{temporary} = " + VIRTUAL_BASE_SLOT + ";$")
    dead = set()
    for index, line in enumerate(lines):
        if store.match(line) and next_store_kills(lines, index, temporary):
            dead.add(index)
    return "\n".join(line for index, line in enumerate(lines) if index not in dead)


def next_store_kills(lines: list, index: int, temporary: str) -> bool:
    depth = indentation_of(lines[index])
    for line in lines[index + 1:]:
        if not line.strip():
            continue
        if indentation_of(line) < depth or re.match(r"^\s*((\w+|case [^:]+|default)\s*:\s*$|goto\b|break;|continue;)", line):
            return False
        if indentation_of(line) == depth and re.match(rf"^\s*{temporary} = ", line):
            return not re.search(rf"\b{temporary}\b", line.split("=", 1)[1])
        if re.search(rf"\b{temporary}\b", line):
            return False
    return False


def substitute_temporary(text: str, temporary: str, base: str) -> str:
    return re.sub(ENCLOSED.format(THIS_ADDRESS + re.escape(temporary) + r"\b"), f"(long){helper_name(base)}()", text)


SIMPLE_STATEMENT = re.compile(r"^\s*(?!(if|else|while|for|do|switch|case|default|return|goto|break|continue)\b)[^{}]*;$")


def fold_in_straight_lines(text: str, temporary: str, virtual_bases: set) -> str:
    lines = text.split("\n")
    assignment = re.compile(rf"^(\s*){temporary} = " + VIRTUAL_BASE_SLOT + ";$")
    for index, line in enumerate(lines):
        match = assignment.match(line)
        if not match or match.group(2) not in virtual_bases:
            continue
        indentation = match.group(1)
        following = index + 1
        while following < len(lines) and SIMPLE_STATEMENT.match(lines[following]) and lines[following].startswith(indentation) and not lines[following].startswith(indentation + " "):
            lines[following] = substitute_temporary(lines[following], temporary, match.group(2))
            if re.match(rf"^\s*{temporary}\s*=[^=]", lines[following]):
                break
            following += 1
    return "\n".join(lines)


def drop_unused_temporary(text: str, temporary: str) -> str:
    """Drop the vtable slot reads into a local nothing reads any more, and its declaration.

    A read that leads a comma expression ('(t = ADJ(this->vptr)->BOffset,x = f(), ...)')
    goes as well, the rest of the expression stays.
    """
    store = re.compile(rf"^\s*{temporary} = " + VIRTUAL_BASE_SLOT + ";$")
    comma_store = re.compile(rf"\b{temporary} = " + VIRTUAL_BASE_SLOT + r",\s*")
    kept = []
    for line in text.split("\n"):
        declaration = DECLARATION.match(line)
        if store.match(line) or (declaration and declaration.group(2) == temporary):
            continue
        line = comma_store.sub("", line)
        if re.search(rf"\b{temporary}\b", line):
            return text
        kept.append(line)
    return "\n".join(kept)


def rewrite_virtual_calls(text: str, virtual_bases: set, slot_names: dict) -> str:
    """Virtual calls through a base helper or this's own vtable become member calls."""

    def through_base(match):
        helper = match.group("cast_helper") or match.group("helper")
        slot, argument_helper, rest = int(match.group("slot"), 16), match.group("argument"), match.group("rest")
        base = next((name for name in virtual_bases if helper_name(name) == helper), None)
        name = slot_names.get((base, slot))
        if base is None or helper != argument_helper or not name:
            return match.group(0)
        return f"{helper}()->{name}(" + ("" if rest == "," else ")")

    text = re.sub(
        r"\(\*\*\(code \*\*\)\(\*\(long \*\)(?:\(\(long\)(?P<cast_helper>\w+)\(\)\)|(?P<helper>\w+)\(\)) \+ (?P<slot>0x[0-9a-f]+)\)\)"
        r"\(\(long\)(?P<argument>\w+)\(\)(?P<rest>,|\))",
        through_base, text)
    text = re.sub(r"\(\*\(code \*\)ADJ\(this->vptr\)->(\w+)\)\(this\)", r"\1()", text)
    return re.sub(r"\(\*\(code \*\)ADJ\(this->vptr\)->(\w+)\)\(this,", r"\1(", text)


def rewrite_base_member_calls(text: str, virtual_bases: set, static_names: frozenset = frozenset()) -> str:
    """B::Method(b(),args) and B::Method(b()) become b()->Method(args); static members stay as they are."""

    def replace(match):
        class_name, method, helper, rest = match.group(1), match.group(2), match.group(3), match.group(4)
        if class_name not in virtual_bases or helper_name(class_name) != helper or f"{class_name}::{method}" in static_names:
            return match.group(0)
        return f"{helper}()->{method}(" + ("" if rest == "," else ")")

    return re.sub(r"\b(C\w+)::(~?\w+)\((\w+)\(\)(,|\))", replace, text)


def rewrite_own_member_calls(text: str, own_methods: set) -> str:
    """Method(this,args) and Method(this) on the current class become Method(args)."""

    def replace(match):
        name, rest = match.group(1), match.group(2)
        if name not in own_methods:
            return match.group(0)
        return f"{name}(" + ("" if rest == "," else ")")

    return re.sub(r"(?<![\w:>.])(~?\w+)\(this(,|\))", replace, text)


def annotate_registry_keys(text: str, keys: dict) -> str:
    """registry()->Accessor() gets the plist key when the key differs from the accessor's name."""

    def replace(match):
        key = keys.get(match.group(1))
        if key is None or key == match.group(1):
            return match.group(0)
        return f'{match.group(0)} /* plist key "{key}" */'

    return re.sub(r"registry\(\)->(\w+)\(\)", replace, text)


def annotate_property_entries(text: str, entries: dict) -> str:
    """A line that reads m_prop[n] gets the plist key of entry n as a trailing comment."""
    lines = []
    for line in text.split("\n"):
        keys = [entries[int(index, 0)] for index in re.findall(r"\bm_prop\[(0x[0-9a-f]+|\d+)\]", line) if int(index, 0) in entries]
        lines.append(line + "  // plist key " + ", ".join(f'"{key}"' for key in keys) if keys else line)
    return "\n".join(lines)


def accessor_keys(functions: list, registry_entries: dict) -> dict:
    """{accessor name: plist key} from 'm_prop[0x66].index' in each CRegistry accessor."""
    keys = {}
    for function in functions:
        if function.qualified_name.startswith("CRegistry::"):
            entries = set(re.findall(r"\bm_prop\[(0x[0-9a-f]+|\d+)\]\.index", function.definition))
            if len(entries) == 1:
                keys[function.qualified_name.split("::")[1]] = registry_entries.get(int(entries.pop(), 0))
    return {name: key for name, key in keys.items() if key}


# ---- locals ---------------------------------------------------------------------

DECLARATION = re.compile(r"^  ([\w ]+?[\s\*]+)(\w+)( \[[^\]]*\])?;$")


def split_body(text: str) -> tuple:
    """(head up to and including '{', declaration lines, the rest) of a function definition."""
    lines = text.split("\n")
    if "{" not in lines:
        return lines, [], []
    brace = lines.index("{")
    declarations = []
    index = brace + 1
    while index < len(lines) and DECLARATION.match(lines[index]):
        declarations.append(lines[index])
        index += 1
    return lines[:brace + 1], declarations, lines[index:]


def declared_types(declarations: list) -> dict:
    types = {}
    for line in declarations:
        match = DECLARATION.match(line)
        if match and not match.group(3):
            types[match.group(2)] = match.group(1).strip()
    return types


def parameter_types(head: list) -> dict:
    """{name: type} of the parameters in the definition line, this included."""
    match = re.search(r"\((.*)\)\s*$", " ".join(head[:-1]))
    if not match:
        return {}
    types = {}
    for parameter in match.group(1).split(","):
        parameter = parameter.strip()
        name_match = re.match(r"^(.*?[\s\*]+)(\w+)$", parameter)
        if name_match:
            types[name_match.group(2)] = name_match.group(1).strip()
    return types


def is_modified(body: str, name: str) -> bool:
    """Whether name is assigned, incremented or has its address taken anywhere in body."""
    assigned = re.search(rf"(?<![\w.>*])\b{name}\s*([-+*/%&|^]|<<|>>)?=(?!=)", body)
    stepped = re.search(rf"(\+\+|--)\s*\b{name}\b|\b{name}\b\s*(\+\+|--)", body)
    address = re.search(rf"&\s*{name}\b(?!\s*(->|\.|\[))", body)
    return bool(assigned or stepped or address)


def fold_parameter_spills(text: str) -> str:
    """'local_14 = param_1;' with equal types and neither side changed: use param_1 throughout."""
    head, declarations, rest = split_body(text)
    locals_by_type = declared_types(declarations)
    parameters = parameter_types(head)
    for line in list(rest):
        match = re.match(r"^  (local_\w+) = (param_\d+|this);$", line)
        if not match:
            continue
        local, parameter = match.group(1), match.group(2)
        others = "\n".join(other for other in rest if other is not line)
        first_mention = next(other for other in rest if re.search(rf"\b{local}\b", other))
        if first_mention is not line or locals_by_type.get(local) != parameters.get(parameter):
            continue
        if is_modified(others, local) or is_modified(others, parameter):
            continue
        rest = [re.sub(rf"\b{local}\b", parameter, other) for other in rest if other is not line]
        declarations = [declaration for declaration in declarations if DECLARATION.match(declaration).group(2) != local]
    return "\n".join(head + declarations + rest)


def drop_dead_locals(text: str) -> str:
    """Drop locals only declared, or only assigned a plain name or constant and never read."""
    head, declarations, rest = split_body(text)
    body = "\n".join(rest)
    kept = []
    for declaration in declarations:
        name = DECLARATION.match(declaration).group(2)
        mentions = [line for line in rest if re.search(rf"\b{name}\b", line)]
        dead_stores = [line for line in mentions if re.match(rf"^\s*{name} = [\w.]+;$", line)]
        if len(mentions) == len(dead_stores) and not re.search(rf"&\s*{name}\b", body):
            rest = [line for line in rest if line not in dead_stores]
            continue
        kept.append(declaration)
    if len(kept) == 0 and rest and rest[0] == "  ":
        rest = rest[1:]
    return "\n".join(head + kept + rest)


# ---- definition line ------------------------------------------------------------


def rewrite_definition_line(text: str, inline: bool) -> str:
    """Drop __thiscall and the explicit this parameter; mark header bodies inline."""
    head, separator, rest = text.partition("\n")
    head = re.sub(r" __thiscall ", " ", head)
    head = re.sub(r"\((\w+) \*this,", "(", head)
    head = re.sub(r"\((\w+) \*this\)", "(void)", head)
    if inline:
        head = "inline " + head
    return head + separator + rest


def method_declaration(function: Function, static: bool, virtual: bool) -> str:
    """'bool MotorSel(int);' from the demangled name and the decompiled return type."""
    return_type = "" if is_structor(function) else definition_return_type(function.definition)
    method = function.demangled.split("::", 1)[1] if "::" in function.demangled else function.qualified_name.split("::")[-1] + "()"
    prefix = "static " if static else "virtual " if virtual else ""
    return f"{prefix}{return_type + ' ' if return_type else ''}{method};"


def definition_return_type(definition: str) -> str:
    """'bool' from 'bool __thiscall CAsic::MotorSel(...)'."""
    head = definition.split("\n", 1)[0].replace("__thiscall ", "")
    match = re.match(r"^(.*?)\s*(\w+::)*~?\w+\(", head)
    return match.group(1).strip() if match else ""


def rewrite_function(function: Function, context: dict, inline: bool) -> str:
    """All rewrites of one function, in order."""
    class_name = class_of(function.qualified_name)
    virtual_bases = context["virtual_bases"].get(class_name, set())
    text = join_wrapped_lines(function.definition)
    text = rewrite_definition_line(text, inline)
    text = normalize_adjusted_access(text)
    text = fold_virtual_base_temporaries(text, virtual_bases)
    text = rewrite_virtual_base_casts(text, virtual_bases)
    text = rewrite_virtual_base_addresses(text, virtual_bases)
    text = rewrite_virtual_base_fields(text, virtual_bases, context["structure_lengths"].get(class_name))
    text = rewrite_virtual_calls(text, virtual_bases, context["slot_names"])
    text = rewrite_base_member_calls(text, virtual_bases, context["static_member_names"])
    text = rewrite_own_member_calls(text, context["methods"].get(class_name, set()) - context["free_function_names"])
    text = annotate_registry_keys(text, context["registry_keys"])
    text = annotate_property_entries(text, context["registry_entries"])
    text = fold_parameter_spills(text)
    return drop_dead_locals(text)


# ---- rendering ------------------------------------------------------------------


def banner(path: str, description: str, reconstructed: list = ()) -> str:
    lines = [
        f"// {path}: {description}",
        f"// Generated by {GENERATOR} from the Ghidra output of the macOS engine",
        "// (ScanApi 1.4.27.4.0, x86_64 slice). Function, class and m_ names come from",
        "// the binary's symbols; names marked \"reconstructed\" are ours (engine/CLAUDE.md).",
    ]
    if reconstructed:
        lines.append(f"// Reconstructed names used in this file: {', '.join(reconstructed)}.")
    lines.append("// Regenerate into a scratch directory and diff before merging (engine/CLAUDE.md).")
    return "\n".join(lines) + "\n"


def reconstructed_names(texts: list, context: dict) -> list:
    """The virtual base helpers and reconstructed members that the given function texts use."""
    body = "\n".join(texts)
    helpers = sorted({helper_name(base) for bases in context["virtual_bases"].values() for base in bases})
    used = [f"{helper}()" for helper in helpers if re.search(rf"\b{helper}\(\)", body)]
    members = sorted({member.name for member in context["members"] if member.comment.startswith("reconstructed")})
    used += [member for member in members if re.search(rf"(->|\.){member}\b", body)]
    used += [f"m_prop[].{field}" for field in ("key", "valueCount", "index") if re.search(rf"\bm_prop\[[^\]]*\]\.{field}\b", body)]
    return used


def render_function(function: Function, text: str) -> str:
    signature = function.demangled or function.qualified_name
    return f"// at 0x{function.address:06x}\n// {signature}\n{text}\n"


def render_source_file(path: str, units: list, functions: list, context: dict) -> str:
    description = f"compile unit {', '.join(units)}" if units else "functions without an entry in the binary's debug map (stubs and externals)"
    parts = [banner(path, description, reconstructed_names([text for _, text in functions], context))]
    parts += [render_function(function, text) for function, text in functions]
    return "\n".join(parts)


def class_declaration(class_name: str, context: dict) -> str:
    bases = [relation for relation in context["relations"] if relation.class_name == class_name and relation.relation in ("base", "virtual base")]
    inheritance = ", ".join(f"public {'virtual ' if relation.relation == 'virtual base' else ''}{relation.base}" for relation in bases)
    lines = [f"class {class_name}" + (f" : {inheritance}" if inheritance else ""), "{", "public:"]
    lines += virtual_base_helper_lines(class_name, context)
    lines += member_lines(class_name, context)
    lines += method_lines(class_name, context)
    lines.append("};")
    return "\n".join(lines) + "\n"


def virtual_base_helper_lines(class_name: str, context: dict) -> list:
    relations = sorted(
        (relation for relation in context["relations"] if relation.class_name == class_name and relation.vtable_slot is not None),
        key=lambda relation: -relation.vtable_slot,
    )
    if not relations:
        return []
    lines = ["    // Reconstructed helpers (not in the binary): the virtual base subobjects, which the", "    // code reaches as this + (offset in vtable slot), printed by Ghidra as ADJ(this->vptr)->BaseOffset."]
    for relation in relations:
        lines.append(f"    {relation.base} *{helper_name(relation.base)}();  // reconstructed, vtable slot -0x{-relation.vtable_slot:x}")
    return lines + [""]


def member_lines(class_name: str, context: dict) -> list:
    members = [member for member in context["members"] if member.class_name == class_name]
    if not members:
        return []
    lines = ["    // Data members the code reveals, at their offsets in the object (ApplyEngineTypes.java)."]
    for member in sorted(members, key=lambda member: member.offset):
        lines.append(member_line(member))
    return lines + [""]


def member_line(member: Member) -> str:
    """One member as C++; the vtable pointer is compiler generated and shown as a comment."""
    if member.name == "vptr":
        return f"    // +0x0: vtable pointer (compiler generated; Ghidra names it vptr, type {member.type_name})"
    array = re.match(r"^(.*)\[(\d+)\]$", member.type_name)
    declaration = f"{array.group(1)} {member.name}[{array.group(2)}]" if array else f"{member.type_name} {member.name}"
    return f"    {declaration};  // +0x{member.offset:x}: {member.comment}"


def method_lines(class_name: str, context: dict) -> list:
    """One declaration per method; the variants a compiler emits (C1/C2, D0/D1/D2, thunks) share it."""
    groups = collections.OrderedDict()
    for function, placement in context["placements_by_class"].get(class_name, []):
        key = method_signature(function)
        groups.setdefault(key, []).append((function, placement))
    lines = ["    // Methods in address order of their first variant, with the file that holds each body."]
    for variants in groups.values():
        lines.append(method_line(variants, context))
    return lines


def method_signature(function: Function) -> str:
    """'MotorSel(int)' from the demangled name, the same for a method and its thunks."""
    if "::" in function.demangled:
        return function.demangled.split("::", 1)[1]
    return function.qualified_name.split("::")[-1] + "()"


def method_line(variants: list, context: dict) -> str:
    representative = next((function for function, _ in variants if symbol_variant(context["symbols"].get(function.address, "")) != "thunk"), variants[0][0])
    virtual = any(function.address in context["virtual_functions"] for function, _ in variants) or any(
        symbol_variant(context["symbols"].get(function.address, "")) == "thunk" for function, _ in variants)
    declaration = method_declaration(representative, representative.address in context["static_members"], virtual)
    where = ", ".join(variant_location(function, context) for function, _ in variants)
    paths = sorted({placement.path for _, placement in variants})
    return f"    {declaration}  // {where}; {', '.join(paths)}"


def variant_location(function: Function, context: dict) -> str:
    variant = symbol_variant(context["symbols"].get(function.address, ""))
    return f"{variant + ' ' if variant else ''}at 0x{function.address:06x}"


STRUCTOR_VARIANTS = {"C1": "C1 complete", "C2": "C2 base object", "D0": "D0 deleting", "D1": "D1 complete", "D2": "D2 base object"}


def symbol_variant(symbol: str) -> str:
    """'C2 base object' for '__ZN5CAsicC2Ev', 'thunk' for a virtual or this-adjusting thunk, else ''."""
    if symbol.startswith(("__ZTv", "__ZTh", "__ZTc")):
        return "thunk"
    match = re.match(r"^__ZN(\d+)", symbol)
    if not match:
        return ""
    after_class = symbol[match.end() + int(match.group(1)):]
    return STRUCTOR_VARIANTS.get(after_class[:2], "") if after_class[2:3] == "E" else ""


def base_includes(class_name: str, context: dict, headers: dict) -> list:
    """Reconstructed #include lines for the headers of the direct bases."""
    bases = [relation.base for relation in context["relations"] if relation.class_name == class_name and relation.relation in ("base", "virtual base")]
    return [f'#include "{os.path.basename(headers.get(base, default_header(base)))}"  // reconstructed: header of the base class' for base in bases]


def render_header(path: str, class_names: list, functions: list, context: dict) -> str:
    includes = []
    for class_name in class_names:
        includes += [line for line in base_includes(class_name, context, context["headers"]) if line not in includes]
    description = "class declarations and inline definitions (weak symbols) of " + ", ".join(class_names) if class_names else "inline functions"
    if path not in context["headers"].values():
        description += " (file name reconstructed: the debug map names no header for this class)"
    if path in context["other_header_spellings"]:
        description += f" (chosen over {', '.join(context['other_header_spellings'][path])}, which the debug map also names, because it matches the class name)"
    parts = [banner(path, description, reconstructed_names([text for _, text in functions], context)), "#pragma once\n" + ("\n".join(includes) + "\n" if includes else "")]
    parts += [class_declaration(class_name, context) for class_name in class_names]
    if functions:
        parts.append("// Inline definitions, in address order.\n")
    parts += [render_function(function, text) for function, text in functions]
    return "\n".join(parts)


def render_architecture(context: dict, unit_counts: dict, purposes: dict) -> str:
    lines = [
        "# Architecture of the macOS engine",
        "",
        f"Generated by `{GENERATOR}` from the binary's tables (`macho_source_map.py`, `macho_engine_tables.py`) and the Ghidra output. Addresses are in the x86_64 slice of `ScanApi` 1.4.27.4.0. The class purposes are quoted from `doc/vendor-driver/macos.md` of the public repository where it has one.",
        "",
        "## Compile units",
        "",
        "Functions per compile unit from the debug map, split into out-of-line definitions (the `.cpp`) and inline ones (weak definitions with hidden visibility, which the reconstruction puts into the class headers).",
        "",
        "| Unit | Functions | Out of line | Inline |",
        "|---|---|---|---|",
    ]
    for unit, counts in sorted(unit_counts.items()):
        lines.append(f"| `{unit}` | {counts['total']} | {counts['total'] - counts['inline']} | {counts['inline']} |")
    lines += entry_point_lines(context)
    lines += ["", "## Classes", "", "Inheritance from the type information records (`__ZTI*`), virtual base slots and offsets from the vtables (`macho_engine_tables.py`). The offset is where the base sits in a complete object of the class. Every base is public.", ""]
    for class_name in sorted(context["class_names"]):
        lines += class_section(class_name, context, purposes.get(class_name))
    return "\n".join(lines) + "\n"


def entry_point_lines(context: dict) -> list:
    """The api* functions, the engine's exported entry points, with address and file."""
    entries = [(function, placement) for function, placement in context["free_placements"] if function.qualified_name.startswith("api")]
    if not entries:
        return []
    listed = ", ".join(f"`{function.qualified_name}` (`0x{function.address:06x}`)" for function, _ in entries)
    files = ", ".join(f"`{path}`" for path in sorted({placement.path for _, placement in entries}))
    return ["", "## Entry points", "", f"{len(entries)} `api*` functions, in {files}: {listed}."]


def class_section(class_name: str, context: dict, purpose) -> list:
    relations = [relation for relation in context["relations"] if relation.class_name == class_name and relation.base]
    direct = [f"`{relation.base}`" + (" (virtual)" if relation.relation == "virtual base" else "") for relation in relations if relation.relation in ("base", "virtual base")]
    virtual = [f"`{relation.base}` (slot -0x{-relation.vtable_slot:x}, offset {relation.offset}, `{helper_name(relation.base)}()`)" for relation in relations if relation.vtable_slot is not None]
    functions = context["placements_by_class"].get(class_name, [])
    files = sorted({placement.path for _, placement in functions})
    lines = [f"### {class_name}", ""]
    if purpose:
        lines.append(f"Purpose: {purpose}")
        lines.append("")
    lines.append(f"Direct bases: {', '.join(direct) if direct else 'none'}.")
    lines.append("")
    if virtual:
        lines.append(f"Virtual bases, direct and indirect: {', '.join(virtual)}.")
        lines.append("")
    constructors = [function for function, _ in functions if function.qualified_name == f"{class_name}::{class_name}"]
    lines.append(f"Functions: {len(functions)}, in {', '.join(f'`{path}`' for path in files) if files else 'no file'}. Constructors at {', '.join(f'`0x{function.address:06x}`' for function in constructors) or 'none found'}.")
    lines.append("")
    slots = sorted((slot, name) for (owner, slot), name in context["slot_names"].items() if owner == class_name)
    if slots:
        lines.append("Own vtable: " + ", ".join(f"0x{slot:x} `{name}`" for slot, name in slots) + ".")
        lines.append("")
    calls = context["calls_by_class"].get(class_name)
    if calls:
        lines.append("Calls into (call sites in the reconstructed text): " + ", ".join(f"`{callee}` {count}" for callee, count in calls.most_common()) + ".")
        lines.append("")
    return lines


def called_classes(text: str, virtual_bases: set) -> collections.Counter:
    """Call sites per class in one rewritten body: helper()->Method( and Class::Method(."""
    by_helper = {helper_name(base): base for base in virtual_bases}
    counter = collections.Counter(by_helper[helper] for helper in re.findall(r"\b(\w+)\(\)->\w+\(", text) if helper in by_helper)
    counter.update(re.findall(r"\b(C[A-Z]\w*)::~?\w+\(", text))
    return counter


# ---- main -----------------------------------------------------------------------


def build_context(functions: list, entries: dict, relations: list, members: list, vtable_rows: list, registry_rows: list) -> dict:
    names_by_address = {function.address: function.qualified_name for function in functions}
    virtual_bases = collections.defaultdict(set)
    for relation in relations:
        if relation.vtable_slot is not None:
            virtual_bases[relation.class_name].add(relation.base)
    methods = collections.defaultdict(set)
    for function in functions:
        class_name = class_of(function.qualified_name)
        if class_name:
            methods[class_name].add(function.qualified_name.split("::")[-1])
    return {
        "names_by_address": names_by_address,
        "virtual_bases": virtual_bases,
        "methods": methods,
        "relations": relations,
        "members": members,
        "slot_names": vtable_slot_names(vtable_rows, names_by_address),
        "virtual_functions": {int(row["address"], 16) for row in vtable_rows},
        "registry_keys": accessor_keys(functions, registry_keys_by_entry(registry_rows)),
        "registry_entries": registry_keys_by_entry(registry_rows),
        "class_names": {relation.class_name for relation in relations},
        "static_members": set(),
        "placements_by_class": collections.defaultdict(list),
        "calls_by_class": collections.defaultdict(collections.Counter),
        "free_placements": [],
    }


def static_member_addresses(functions: list) -> set:
    """Members whose definition has no __thiscall (ApplyEngineTypes.java left them static)."""
    return {
        function.address
        for function in functions
        if class_of(function.qualified_name) and "__thiscall" not in function.definition.split("\n", 1)[0] and not is_structor(function)
    }


def is_structor(function: Function) -> bool:
    class_name, _, method = function.qualified_name.partition("::")
    return method in (class_name, "~" + class_name)


def unit_function_counts(entries: dict) -> dict:
    counts = collections.defaultdict(lambda: {"total": 0, "inline": 0})
    for entry in entries.values():
        counts[entry.compile_unit]["total"] += 1
        counts[entry.compile_unit]["inline"] += entry.linkage == "inline"
    return counts


def write_file(root: str, path: str, text: str) -> None:
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as handle:
        handle.write(text)


def load_context(arguments) -> tuple:
    """(functions, map entries, context) from the input files."""
    functions = read_decompiled(arguments.decompiled)
    entries = parse_map_rows(read_tsv(arguments.source_map))
    relations = parse_class_rows(read_tsv(arguments.classes))
    member_rows = read_tsv(arguments.members) if arguments.members else []
    context = build_context(functions, entries, relations, parse_member_rows(member_rows), read_tsv(arguments.vtables), read_tsv(arguments.registry_keys))
    context["structure_lengths"] = structure_lengths(member_rows)
    context["static_members"] = static_member_addresses(functions)
    context["static_member_names"] = frozenset(function.qualified_name for function in functions if function.address in context["static_members"])
    context["free_function_names"] = {function.qualified_name for function in functions if class_of(function.qualified_name) is None}
    context["headers"] = class_headers(entries, context["names_by_address"])
    context["other_header_spellings"] = other_header_spellings(entries, context["names_by_address"])
    context["symbols"] = {address: entry.symbol for address, entry in entries.items()}
    return functions, entries, context


def place_and_rewrite(functions: list, entries: dict, context: dict) -> tuple:
    """({path: [(function, rewritten text)]}, {source path: compile units}), noting placements and calls in the context."""
    directories = unit_directories(entries)
    files = collections.defaultdict(list)
    units_by_path = collections.defaultdict(set)
    for function in functions:
        entry = entries.get(function.address)
        placement = place_function(function, entry, directories, context["headers"])
        rewritten = rewrite_function(function, context, placement.inline)
        files[placement.path].append((function, rewritten))
        if entry and not placement.inline:
            units_by_path[placement.path].add(entry.compile_unit)
        record_placement(function, placement, rewritten, context)
    return files, units_by_path


def record_placement(function: Function, placement: Placement, rewritten: str, context: dict) -> None:
    """Note where a function went and which classes it calls, for architecture.md."""
    class_name = class_of(function.qualified_name)
    if not class_name:
        context["free_placements"].append((function, placement))
        return
    context["placements_by_class"][class_name].append((function, placement))
    body = rewritten.split("\n", 1)[1] if "\n" in rewritten else ""
    context["calls_by_class"][class_name].update(called_classes(body, context["virtual_bases"].get(class_name, set())))


def render_tree(files: dict, units_by_path: dict, context: dict) -> dict:
    """{macos/<path>: text} for every source and header, with a header for every class even without inline functions."""
    header_classes = collections.defaultdict(list)
    for class_name in sorted(context["class_names"]):
        header_classes[context["headers"].get(class_name, default_header(class_name))].append(class_name)
    output = {}
    for path in set(files) | set(header_classes):
        if path.startswith("Includes/"):
            output["macos/" + path] = render_header(path, header_classes.get(path, []), files.get(path, []), context)
        else:
            output["macos/" + path] = render_source_file(path, sorted(units_by_path[path]), files[path], context)
    return output


def generate(arguments) -> dict:
    """{relative output path: text} for the whole tree."""
    functions, entries, context = load_context(arguments)
    files, units_by_path = place_and_rewrite(functions, entries, context)
    output = render_tree(files, units_by_path, context)
    with open(arguments.class_notes) as handle:
        purposes = class_purposes(handle.read(), context["class_names"])
    output["notes/architecture.md"] = render_architecture(context, unit_function_counts(entries), purposes)
    return output


def parse_arguments(command_line: list):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--decompiled", required=True, help="directory written by DecompileMatching.java")
    parser.add_argument("--output", required=True, help="root of the tree (engine/ or a scratch directory)")
    parser.add_argument("--source-map", default="work/re/source-map-x86_64.tsv")
    parser.add_argument("--classes", default="work/re/classes-x86_64.tsv")
    parser.add_argument("--vtables", default="work/re/vtables-x86_64.tsv")
    parser.add_argument("--registry-keys", default="work/re/registry-keys-x86_64.tsv")
    parser.add_argument("--members", default="work/re/members-x86_64.tsv", help="class members from ApplyEngineTypes.java, empty to skip")
    parser.add_argument("--class-notes", default="doc/vendor-driver/macos.md")
    return parser.parse_args(command_line)


def main(command_line: list) -> int:
    arguments = parse_arguments(command_line)
    output = generate(arguments)
    for path, text in sorted(output.items()):
        write_file(arguments.output, path, text)
    print(f"wrote {len(output)} files under {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
