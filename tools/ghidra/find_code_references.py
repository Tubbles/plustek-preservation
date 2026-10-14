"""Look for references to functions of a 64-bit PE file that a disassembler may
have missed, to back up a "no caller" result.

For each target virtual address it reports:
- E8 (call) and E9 (jmp) rel32 instructions in executable sections whose
  target is the address, tried at every byte offset, so also in bytes the
  disassembler did not reach (false positives are possible);
- every place in the file that holds the address as a 64-bit pointer or as a
  32-bit RVA, with the section it lies in. An RVA in .pdata is the function's
  own unwind entry, not a caller. RVA-sized matches inside code are usually
  coincidental (for example a RIP-relative displacement that happens to have
  the same value) and need a look at the disassembly.

Usage: find_code_references.py <pe file> <target va hex> ...
"""
import struct
import sys


def sections(data):
    pe_offset = struct.unpack_from('<I', data, 0x3c)[0]
    count = struct.unpack_from('<H', data, pe_offset + 6)[0]
    optional_size = struct.unpack_from('<H', data, pe_offset + 20)[0]
    image_base = struct.unpack_from('<Q', data, pe_offset + 24 + 24)[0]
    table = pe_offset + 24 + optional_size
    result = []
    for index in range(count):
        entry = table + 40 * index
        name = data[entry:entry + 8].rstrip(b'\0').decode('latin-1')
        virtual_address, raw_size, raw_offset = struct.unpack_from('<III', data, entry + 12)
        characteristics = struct.unpack_from('<I', data, entry + 36)[0]
        result.append((name, image_base + virtual_address, raw_offset, raw_size, characteristics))
    return image_base, result


def section_name_at(section_list, file_offset):
    for name, _, raw_offset, raw_size, _ in section_list:
        if raw_offset <= file_offset < raw_offset + raw_size:
            return name
    return 'headers'


def relative_branches(data, section_list, targets):
    for name, va, raw_offset, raw_size, characteristics in section_list:
        if not characteristics & 0x20000000:
            continue
        for offset in range(raw_offset, raw_offset + raw_size - 5):
            if data[offset] in (0xe8, 0xe9):
                site = va + offset - raw_offset
                target = site + 5 + struct.unpack_from('<i', data, offset + 1)[0]
                if target in targets:
                    yield target, '%s %x' % ('call' if data[offset] == 0xe8 else 'jmp', site)


def stored_values(data, section_list, image_base, targets):
    for target in targets:
        for kind, pattern in (('ptr64', struct.pack('<Q', target)), ('rva32', struct.pack('<I', target - image_base))):
            offset = data.find(pattern)
            while offset != -1:
                yield target, '%s at file offset %x (%s)' % (kind, offset, section_name_at(section_list, offset))
                offset = data.find(pattern, offset + 1)


def main():
    data = open(sys.argv[1], 'rb').read()
    targets = [int(value, 16) for value in sys.argv[2:]]
    image_base, section_list = sections(data)
    found = {target: [] for target in targets}
    for target, text in relative_branches(data, section_list, set(targets)):
        found[target].append(text)
    for target, text in stored_values(data, section_list, image_base, targets):
        found[target].append(text)
    for target in targets:
        print('%x\t%s' % (target, '; '.join(found[target]) or 'nothing'))


main()
