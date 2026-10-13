"""Turn accessor facts from ExtractAccessorFacts.java into a register field table.

Each CGL12x/CGL846 field has a getter "NAME(bool, int)" and usually a setter
"NAME(int, bool, int)". The engine keeps a 16-bit shadow entry per register
(offset = register * 2) and talks to the device through CIOUSB::ReadRegs and
CIOUSB::WriteRegs (register number in the second argument). Multi-byte fields
go through CRegister::SetRegs / GetRegs (register, byte count). Bit fields
are read-modify-write on the shadow: the setter ANDs with the inverted field
mask and shifts the value left; the getter shifts right and ANDs with the
field mask.

Usage:
  python3 -I tools/ghidra/register_fields.py <facts.jsonl> <class> [--markdown]
  python3 -I tools/ghidra/register_fields.py <facts.jsonl> <class> --diff <other class>
"""

import json
import sys

READ_FLAG_MASK = 0x1  # every accessor tests its "access hardware" flag with "& 1"


def load_facts(path):
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def as_int(text):
    return None if text is None else int(text, 16)


def is_getter(fact):
    return fact["signature"].endswith("(bool, int)")


def is_setter(fact):
    return fact["signature"].endswith("(int, bool, int)")


def call_arguments(fact, callee):
    return [call["arguments"] for call in fact["calls"] if call["callee"] == callee]


def multi_byte_register(fact):
    """Register and byte count from CRegister::SetRegs or GetRegs, if any."""
    for arguments in call_arguments(fact, "CRegister::SetRegs"):
        return as_int(arguments[1]), as_int(arguments[3])
    for arguments in call_arguments(fact, "CRegister::GetRegs"):
        return as_int(arguments[1]), as_int(arguments[2])
    return None


def hardware_register(fact):
    """Register named in the ReadRegs, WriteRegs or SetLink call."""
    for callee in ("CIOUSB::WriteRegs", "CIOUSB::ReadRegs", "CRegister::SetLink"):
        for arguments in call_arguments(fact, callee):
            if len(arguments) > 1 and arguments[1] is not None:
                return as_int(arguments[1])
    return None


def shadow_register(fact):
    """Register from 16-bit shadow loads or stores (offset = register * 2)."""
    offsets = {as_int(item["offset"]) for item in fact["memory"] if item["size"] == 2}
    offsets = {offset for offset in offsets if offset < 0x1000}
    if len(offsets) == 1:
        return offsets.pop() // 2
    return None


def strip_read_flag(values):
    remaining = list(values)
    if READ_FLAG_MASK in remaining:
        remaining.remove(READ_FLAG_MASK)
    return remaining


def setter_mask(fact):
    """Field mask from the AND with the inverted mask (0xffXX)."""
    masks = [value for value in map(as_int, fact["and"]) if 0xff00 <= value <= 0xfffe]
    if not masks:
        return None
    return (~masks[0]) & 0xff


def getter_mask(fact):
    shifts = [as_int(value) for value in fact["shift_right"]]
    shift = shifts[0] if shifts else 0
    masks = strip_read_flag([as_int(value) for value in fact["and"]])
    masks = [value for value in masks if value <= 0xff]
    mask = masks[-1] if masks else 0xff >> shift
    return (mask << shift) & 0xff


def describe(fact):
    """Return (kind, register, mask_or_bytes) for one accessor."""
    if not fact["calls"] and not fact["memory"]:
        value = as_int(fact["returns"][0]) if fact["returns"] else None
        return ("stub", None, value)
    multi = multi_byte_register(fact)
    if multi is not None:
        return ("bytes", multi[0], multi[1])
    register = hardware_register(fact)
    if register is None:
        register = shadow_register(fact)
    if is_setter(fact):
        mask = setter_mask(fact)
        if mask is None and fact["shift_left"] == [] and READ_FLAG_MASK in map(as_int, fact["and"]):
            mask = 0xff  # whole register written
        return ("bits", register, mask)
    return ("bits", register, getter_mask(fact))


def field_rows(facts, class_name):
    rows = {}
    for fact in facts:
        if fact.get("class") != class_name or "signature" not in fact:
            continue
        if not (is_getter(fact) or is_setter(fact)):
            continue
        row = rows.setdefault(fact["name"], {"getter": None, "setter": None})
        row["getter" if is_getter(fact) else "setter"] = (fact["address"], describe(fact))
    return rows


def bit_text(mask):
    if mask is None:
        return "?"
    bits = [bit for bit in range(8) if mask >> bit & 1]
    if not bits:
        return "none"
    if bits == list(range(bits[0], bits[-1] + 1)):
        return f"{bits[-1]}" if len(bits) == 1 else f"{bits[-1]}-{bits[0]}"
    return ",".join(str(bit) for bit in reversed(bits))


def merge(row):
    """Combine getter and setter into register, layout text, note."""
    parts = [item[1] for item in (row["getter"], row["setter"]) if item]
    real = [part for part in parts if part[0] != "stub"]
    if not real:
        values = ", ".join("returns ?" if part[2] is None else f"returns {part[2]}" for part in parts)
        return None, "not implemented", values
    kinds = {part[0] for part in real}
    registers = {part[1] for part in real if part[1] is not None}
    note = ""
    if len(registers) > 1 or len(kinds) > 1:
        note = "getter and setter disagree: " + "; ".join(str(part) for part in real)
    register = min(registers) if registers else None
    if "bytes" in kinds:
        count = max(part[2] for part in real if part[0] == "bytes")
        layout = f"{count} bytes, big-endian, `0x{register:02x}` to `0x{register + count - 1:02x}`"
        return register, layout, note
    masks = {part[2] for part in real if part[2] is not None}
    if len(masks) > 1:
        note = (note + " " if note else "") + "masks differ: " + ", ".join(f"0x{m:02x}" for m in sorted(masks))
    mask = max(masks) if masks else None
    layout = f"mask `0x{mask:02x}`, bits {bit_text(mask)}" if mask is not None else "?"
    if any(part[0] == "stub" for part in parts):
        note = (note + " " if note else "") + "one accessor is a stub"
    return register, layout, note


def table(facts, class_name):
    rows = field_rows(facts, class_name)
    result = []
    for name, row in rows.items():
        register, layout, note = merge(row)
        getter = row["getter"][0] if row["getter"] else ""
        setter = row["setter"][0] if row["setter"] else ""
        result.append((register if register is not None else 0x10000, name, layout, getter, setter, note))
    result.sort()
    return result


def markdown(rows):
    lines = ["| Field | Register | Layout | Getter | Setter | Note |",
             "|---|---|---|---|---|---|"]
    for register, name, layout, getter, setter, note in rows:
        register_text = "" if register == 0x10000 else f"`0x{register:02x}`"
        getter_text = f"`0x{int(getter, 16):06x}`" if getter else ""
        setter_text = f"`0x{int(setter, 16):06x}`" if setter else ""
        lines.append(f"| `{name}` | {register_text} | {layout} | {getter_text} | {setter_text} | {note} |")
    return "\n".join(lines)


def differences(facts, first, second):
    first_rows = {row[1]: row for row in table(facts, first)}
    second_rows = {row[1]: row for row in table(facts, second)}
    lines = [f"| Field | {first} | {second} |", "|---|---|---|"]
    for name in sorted(set(first_rows) | set(second_rows)):
        left = first_rows.get(name)
        right = second_rows.get(name)
        left_text = "absent" if left is None else _short(left)
        right_text = "absent" if right is None else _short(right)
        if left_text != right_text:
            lines.append(f"| `{name}` | {left_text} | {right_text} |")
    return "\n".join(lines)


def _short(row):
    register, _, layout, _, _, _ = row
    if layout == "not implemented":
        return "not implemented"
    register_text = "?" if register == 0x10000 else f"`0x{register:02x}`"
    return f"{register_text} {layout}"


def main(arguments):
    facts = load_facts(arguments[0])
    class_name = arguments[1]
    if "--diff" in arguments:
        other = arguments[arguments.index("--diff") + 1]
        print(differences(facts, class_name, other))
        return
    print(markdown(table(facts, class_name)))


if __name__ == "__main__":
    main(sys.argv[1:])
