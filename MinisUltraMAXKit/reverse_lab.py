#!/usr/bin/env python3
"""Minis ReverseLab R5.6: executable, read-only Mach-O arm64e evidence.

Pure Python 3 standard-library core; optional Capstone instruction decoder.
Never executes a supplied binary, writes into it, installs hooks or guesses
Swift field offsets / PAC calling conventions.
"""
import argparse
import hashlib
import json
import mmap
import pathlib
import shutil
import struct
import sys

MAX_SLICES = 32
MAX_COMMANDS = 4096
MAX_SECTIONS = 2048
MAX_SYMBOLS = 300000
MAX_FUNCTIONS = 400000
MAX_BYTES = 1024 * 1024 * 1024
MAGICS = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}
FAT_MAGICS = {b"\xca\xfe\xba\xbe": (">", False), b"\xca\xfe\xba\xbf": (">", True),
              b"\xbe\xba\xfe\xca": ("<", False), b"\xbf\xba\xfe\xca": ("<", True)}
ARM64 = 0x0100000c

class ParseError(ValueError):
    pass

def region(start, length, lower, upper):
    if start < lower or length < 0 or start > upper or length > upper - start:
        raise ParseError("out-of-bounds binary range")
    return start, start + length

def stringz(binary, start, end, max_len=4096):
    if start < 0 or start >= end:
        return ""
    last = min(end, start + max_len)
    b = binary[start:last]
    return bytes(b.split(b"\x00", 1)[0]).decode("utf-8", "replace")

def uleb(data, position, end):
    result = 0
    for shift in range(0, 70, 7):
        if position >= end:
            raise ParseError("truncated ULEB128")
        byte = data[position]
        position += 1
        if shift == 63 and (byte & 0x7f) > 1:
            raise ParseError("ULEB128 overflow")
        result |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return result, position
    raise ParseError("ULEB128 exceeds 64 bits")

def architecture(cpu, subtype):
    cpu &= 0xffffffff
    st = subtype & 0xff
    if cpu == ARM64:
        return "arm64e" if st == 2 else "arm64"
    return {0x01000007: "x86_64", 0x01000012: "arm64_32"}.get(cpu, f"cpu_0x{cpu:08x}")

def ascii_samples(data, start, end, needle, limit=32):
    # Metadata strings only; never dump full __cstring or application secrets.
    region(start, end-start, 0, len(data))
    matches = []
    at = start
    term = (needle or "").lower()
    while at < end and len(matches) < limit:
        finish = data.find(b"\0", at, min(at + 1024, end))
        if finish < 0:
            at = min(at + 1024, end)
            continue
        raw = bytes(data[at:finish])
        if 3 <= len(raw) <= 240 and all(32 <= v <= 126 for v in raw):
            value = raw.decode("ascii")
            if not term or term in value.lower():
                matches.append({"file_offset": at, "text": value})
        at = finish + 1
    return matches

def decode_branch(word, pc):
    # Zero-dependency ARM64 branch evidence, not a general disassembler.
    def sign(value, bits):
        return value - (1 << bits) if value & (1 << (bits - 1)) else value
    if word & 0xfc000000 in (0x14000000, 0x94000000):
        delta = sign(word & 0x03ffffff, 26) << 2
        return {"mnemonic": "bl" if word & 0xfc000000 == 0x94000000 else "b",
                "target": f"0x{(pc + delta) & ((1 << 64) - 1):x}"}
    if word & 0xff000010 == 0x54000000:
        delta = sign((word >> 5) & 0x7ffff, 19) << 2
        return {"mnemonic": "b.cond", "target": f"0x{(pc + delta) & ((1 << 64) - 1):x}"}
    if word & 0x7e000000 == 0x34000000:
        delta = sign((word >> 5) & 0x7ffff, 19) << 2
        return {"mnemonic": "cbnz" if word & 0x01000000 else "cbz",
                "target": f"0x{(pc + delta) & ((1 << 64) - 1):x}"}
    if word & 0x7e000000 == 0x36000000:
        delta = sign((word >> 5) & 0x3fff, 14) << 2
        return {"mnemonic": "tbnz" if word & 0x01000000 else "tbz",
                "target": f"0x{(pc + delta) & ((1 << 64) - 1):x}"}
    return None

def analyze_slice(data, start, length, search="", at=None, count=24):
    region(start, length, 0, len(data))
    end = start + length
    magic = bytes(data[start:start+4])
    if magic not in MAGICS:
        raise ParseError("unsupported thin Mach-O magic (64-bit only)")
    order = MAGICS[magic]
    region(start, 32, start, end)
    header = struct.unpack_from(order + "IiiIIIII", data, start)
    _, cpu, subtype, filetype, ncmds, sizeofcmds, flags, _ = header
    if ncmds > MAX_COMMANDS or sizeofcmds > 16*1024*1024:
        raise ParseError("implausible Mach-O load command counts")
    region(start+32, sizeofcmds, start, end)
    cursor, cmd_end = start+32, start+32+sizeofcmds
    result = {"architecture": architecture(cpu, subtype), "cpu": cpu & 0xffffffff,
              "subtype": subtype & 0xffffffff, "filetype": filetype,
              "flags": flags, "slice_file_offset": start, "slice_size": length,
              "load_command_count": ncmds, "dependencies": [], "sections": [],
              "swift_metadata": {}, "objc_metadata": {}, "warnings": []}
    text_segment = None
    segments = []
    symtab = None
    function_data = None
    cryptids = []
    symbols = []
    for _ in range(ncmds):
        region(cursor, 8, start, cmd_end)
        cmd, cmd_size = struct.unpack_from(order + "II", data, cursor)
        if cmd_size < 8:
            raise ParseError("zero or invalid load command")
        region(cursor, cmd_size, start, cmd_end)
        if cmd == 0x19:  # LC_SEGMENT_64
            if cmd_size < 72:
                raise ParseError("truncated LC_SEGMENT_64")
            seg = stringz(data, cursor+8, cursor+24, 16)
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from(order+"QQQQ", data, cursor+24)
            initprot, nsects = struct.unpack_from(order+"iI", data, cursor+60)
            if nsects > MAX_SECTIONS or 72 + nsects*80 > cmd_size:
                raise ParseError("invalid section table")
            if filesize:
                region(start+fileoff, filesize, start, end)
            if filesize:
                segments.append({"vmaddr":vmaddr,"fileoff":fileoff,"filesize":filesize})
            if seg == "__TEXT":
                text_segment = {"vmaddr": vmaddr, "fileoff": fileoff,
                                "filesize": filesize, "vmsize": vmsize}
            for n in range(nsects):
                p = cursor+72+n*80
                sect = stringz(data, p, p+16, 16)
                sect_seg = stringz(data, p+16, p+32, 16)
                addr, section_size = struct.unpack_from(order+"QQ", data, p+32)
                off = struct.unpack_from(order+"I", data, p+48)[0]
                section_flags = struct.unpack_from(order+"I", data, p+64)[0]
                virtual = (section_flags & 0xff) in (0x01, 0x0c, 0x12)
                if section_size and not virtual:
                    region(start+off, section_size, start, end)
                result["sections"].append({"segment": sect_seg, "name": sect,
                     "vmaddr": f"0x{addr:x}", "size": section_size,
                     "file_offset": off, "virtual_only": virtual})
                if not virtual and section_size and (sect.startswith("__swift5_") or
                                                     sect in ("__objc_classname", "__objc_methname")):
                    samples = ascii_samples(data, start+off, start+off+section_size, search)
                    record = {"size": section_size, "strings": samples}
                    bucket = result["swift_metadata"] if sect.startswith("__swift5_") else result["objc_metadata"]
                    bucket[sect] = record
        elif cmd == 0x2:  # LC_SYMTAB
            if cmd_size < 24: raise ParseError("truncated LC_SYMTAB")
            symtab = struct.unpack_from(order+"IIII", data, cursor+8)
        elif cmd == 0x26:  # LC_FUNCTION_STARTS
            if cmd_size < 16: raise ParseError("truncated LC_FUNCTION_STARTS")
            function_data = struct.unpack_from(order+"II", data, cursor+8)
        elif cmd in (0x21, 0x2c):
            if cmd_size >= 20:
                cryptids.append(struct.unpack_from(order+"I", data, cursor+16)[0])
        elif cmd == 0x1b and cmd_size >= 24:
            result["uuid"] = bytes(data[cursor+8:cursor+24]).hex()
        elif cmd in (0xc, 0x18, 0x80000018, 0x1f, 0x8000001f, 0x23, 0x80000023):
            if cmd_size < 24: raise ParseError("truncated LC_LOAD_DYLIB")
            nameoff = struct.unpack_from(order+"I", data, cursor+8)[0]
            if 24 <= nameoff < cmd_size:
                result["dependencies"].append(stringz(data,cursor+nameoff,cursor+cmd_size))
        cursor += cmd_size
    if cursor != cmd_end:
        raise ParseError("load commands do not span declared sizeofcmds")
    def vm_to_file(vmaddr, size=1):
        for segment in segments:
            relative = vmaddr - segment["vmaddr"]
            if 0 <= relative and size <= segment["filesize"] - relative:
                offset = start + segment["fileoff"] + relative
                region(offset, size, start, end)
                return offset
        return None

    # Swift ABI __swift5_types: each signed 32-bit relative direct pointer
    # references a context descriptor; nominal type kinds class=16,
    # struct=17, enum=18. This is actual metadata extraction, not a
    # regex-only name search or source-code reconstruction.
    nominal_types = []
    swift = next((section for section in result["sections"]
                  if section["name"] == "__swift5_types" and
                  not section["virtual_only"]), None)
    if swift:
        section_addr = int(swift["vmaddr"],16)
        section_offset = start + swift["file_offset"]
        entries = min(swift["size"]//4, 80000)
        for i in range(entries):
            entry_off = section_offset + 4*i
            delta = struct.unpack_from(order+"i",data,entry_off)[0]
            # Swift relative indirectables: low bit 1 marks indirection.
            if delta == 0 or delta & 1:
                continue
            descriptor_addr = section_addr + i*4 + delta
            desc_off = vm_to_file(descriptor_addr, 12)
            if desc_off is None:
                continue
            flags, parent_delta, name_delta = struct.unpack_from(order+"Iii",data,desc_off)
            kind = flags & 0x1f
            if kind not in (16,17,18):
                continue
            name_addr = descriptor_addr + 8 + name_delta
            name_off = vm_to_file(name_addr)
            if name_off is None:
                continue
            name_end = next((start+seg["fileoff"]+seg["filesize"] for seg in segments
                             if seg["vmaddr"] <= name_addr <
                             seg["vmaddr"]+seg["filesize"]), end)
            name = stringz(data,name_off,name_end,240)
            if not name or any(ord(c)<32 for c in name):
                continue
            if search and search.lower() not in name.lower():
                continue
            nominal_types.append({"name":name,"kind":{16:"class",17:"struct",18:"enum"}[kind],
                                 "descriptor_address":f"0x{descriptor_addr:x}",
                                 "context_flags":f"0x{flags:x}"})
            if len(nominal_types)>=160:
                result["warnings"].append("Swift nominal type output limited to 160 matches")
                break
    result["swift_nominal_types"] = nominal_types
    result["encrypted"] = any(cryptids)
    if result["encrypted"]:
        result["warnings"].append("Encrypted segment reported; symbols/metadata may be incomplete")
    if symtab:
        symoff, nsyms, stroff, strsize = symtab
        if nsyms > MAX_SYMBOLS:
            raise ParseError("symbol count exceeds bounded parser limit")
        region(start+symoff, nsyms*16, start, end)
        region(start+stroff, strsize, start, end)
        for j in range(nsyms):
            p = start+symoff+j*16
            strx, ntype, nsect, ndesc, value = struct.unpack_from(order+"IBBHQ", data, p)
            if strx >= strsize or ntype & 0xe0:
                continue
            sym = stringz(data, start+stroff+strx, start+stroff+strsize, 512)
            if not sym:
                continue
            if search and search.lower() not in sym.lower():
                continue
            symbols.append({"name": sym, "address": f"0x{value:x}",
                            "kind": "undefined" if ntype & 0x0e == 0 else "defined",
                            "external": bool(ntype & 1)})
            if len(symbols) >= 100:
                break
        result["symbol_count"] = nsyms
    result["matching_symbols"] = symbols
    starts = []
    if function_data and text_segment:
        off, length_data = function_data
        region(start+off, length_data, start, end)
        cursor2 = start+off
        last = start+off+length_data
        delta_acc = 0
        seen = 0
        while cursor2 < last and seen < MAX_FUNCTIONS:
            v, cursor2 = uleb(data, cursor2, last)
            if v == 0:
                break
            delta_acc += v
            seen += 1
            if seen <= 120:
                starts.append(f"0x{text_segment['vmaddr']+delta_acc:x}")
        result["function_starts"] = {"count_parsed": seen, "samples": starts,
                                    "truncated": seen >= MAX_FUNCTIONS}
    else:
        result["function_starts"] = {"count_parsed": 0, "samples": [],
                                    "note": "No LC_FUNCTION_STARTS with __TEXT"}
    if at is not None:
        if result["architecture"] not in ("arm64", "arm64e"):
            raise ParseError("branch decoder supports only ARM64 / arm64e")
        if not text_segment:
            raise ParseError("__TEXT segment not available")
        vmaddr = text_segment["vmaddr"]
        if (at % 4) or at < vmaddr or at >= vmaddr + text_segment["filesize"]:
            raise ParseError("instruction address must be aligned and inside file-backed __TEXT")
        n = min(count, 128, (vmaddr + text_segment["filesize"] - at)//4)
        offset = start + text_segment["fileoff"] + at - vmaddr
        instructions = []
        try:
            import capstone
            cs = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
            for ins in cs.disasm(bytes(data[offset:offset+n*4]), at):
                instructions.append({"address": f"0x{ins.address:x}",
                                     "mnemonic": ins.mnemonic, "operands": ins.op_str})
                if len(instructions) >= n: break
            result["disassembler"] = "capstone"
        except ImportError:
            result["disassembler"] = "builtin-branch-only"
            result["warnings"].append("Capstone not installed: full instruction disassembly unavailable")
            for k in range(n):
                pc = at + k*4
                word = struct.unpack_from("<I", data, offset+k*4)[0]
                info = decode_branch(word, pc)
                if info:
                    instructions.append({"address": f"0x{pc:x}", **info})
        result["instructions"] = instructions
    result["caveat"] = "Static evidence only: offsets, runtime ASLR, PAC ABI and Swift layout require independent validation"
    return result

def analyze(path, search="", at=None, count=24):
    path = pathlib.Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ParseError("input must be a regular local file, not a symlink")
    if path.stat().st_size < 32 or path.stat().st_size > MAX_BYTES:
        raise ParseError("unsupported input size")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            hasher.update(block)
        stream.seek(0)
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            magic = bytes(data[:4])
            out = {"tool": "Minis ReverseLab R5.6", "file": str(path),
                   "bytes": len(data), "sha256": hasher.hexdigest(), "slices": []}
            if magic in FAT_MAGICS:
                order, is64 = FAT_MAGICS[magic]
                count_slices = struct.unpack_from(order+"I", data, 4)[0]
                if count_slices < 1 or count_slices > MAX_SLICES:
                    raise ParseError("invalid universal-binary slice count")
                entry_size = 32 if is64 else 20
                region(8, entry_size*count_slices, 0, len(data))
                table_end = 8 + entry_size*count_slices
                spans = []
                for i in range(count_slices):
                    p = 8 + i*entry_size
                    if is64:
                        cpu, subtype, offset, size, alignment, reserved = struct.unpack_from(order+"iiQQII",data,p)
                    else:
                        cpu, subtype, offset, size, alignment = struct.unpack_from(order+"iiIII",data,p)
                    if offset < table_end: raise ParseError("slice overlaps universal header")
                    region(offset, size, 0, len(data))
                    if any(offset < aend and astart < offset+size for astart,aend in spans):
                        raise ParseError("overlapping architecture slices")
                    spans.append((offset,offset+size))
                    out["slices"].append(analyze_slice(data, offset, size, search, at, count))
            else:
                out["slices"].append(analyze_slice(data, 0, len(data), search, at, count))
            out["slice_count"] = len(out["slices"])
            return out

def main(argv=None):
    p = argparse.ArgumentParser(description="Offline read-only Mach-O/arm64e evidence extraction")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    for name in ("analyze", "disasm"):
        cmd = sub.add_parser(name)
        cmd.add_argument("file")
        cmd.add_argument("--search", default="", help="Filter extracted metadata/symbol samples")
        cmd.add_argument("--at", type=lambda s:int(s,0), help="Unslid vmaddr, e.g. 0x100010000")
        cmd.add_argument("--count", type=int, default=24)
        cmd.add_argument("--out", help="Optional JSON output (not original input)")
    a = p.parse_args(argv)
    if a.action == "doctor":
        try: import capstone; version = capstone.__version__
        except ImportError: version = None
        print(json.dumps({"python": sys.version.split()[0],
             "capstone": version, "llvm_objdump": shutil.which("llvm-objdump"),
             "built_in": ["Mach-O 64/fat parsing", "Swift/ObjC section and symbol scanning",
                          "function starts", "ARM64 branch targets"],
             "full_disassembly": bool(version), "runtime_hooking": False},indent=2))
        return 0
    try:
        if a.count < 1 or a.count > 128: raise ParseError("count must be between 1 and 128")
        if a.action == "disasm" and a.at is None:
            raise ParseError("disasm requires --at 0xADDRESS")
        report = analyze(a.file, a.search[:128], a.at, a.count)
        blob = json.dumps(report,ensure_ascii=False,indent=2) + "\n"
        if a.out:
            destination = pathlib.Path(a.out).expanduser()
            if destination.resolve() == pathlib.Path(a.file).resolve() or destination.is_symlink():
                raise ParseError("output path must not overwrite input")
            if destination.exists():
                raise ParseError("output file already exists")
            destination.write_text(blob,encoding="utf-8")
        else:
            print(blob,end="")
        return 0
    except (OSError,ParseError,struct.error) as exc:
        print("NO-GO ReverseLab: "+str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
