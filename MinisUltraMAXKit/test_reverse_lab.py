"""ReverseLab R5.6: real synthetic Mach-O metadata / malformed file regressions."""
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import reverse_lab as rev

VM = 0x1000
def padded(s):
    return s.encode().ljust(16,b"\0")
def section(name,offset,size,flags=0):
    return struct.pack("<16s16sQQIIIIIIII",padded(name),padded("__TEXT"),VM+offset,
                       size,offset,2,0,0,flags,0,0,0)
def fixture(subtype=2):
    buf = bytearray(0x1000)
    seg = struct.pack("<II16sQQQQiiII",0x19,72+3*80,padded("__TEXT"),
                      VM,len(buf),0,len(buf),7,5,3,0)
    seg += section("__text",0x400,12,0x80000400)
    seg += section("__swift5_types",0x500,4)
    seg += section("__objc_classname",0x680,16)
    sym = struct.pack("<IIIIII",2,24,0x700,1,0x750,48)
    func = struct.pack("<IIII",0x26,16,0x810,3)
    uuid = struct.pack("<II16s",0x1b,24,b"0123456789abcdef")
    commands=seg+sym+func+uuid
    struct.pack_into("<IiiIIIII",buf,0,0xfeedfacf,rev.ARM64,subtype,6,4,
                     len(commands),0,0)
    buf[32:32+len(commands)] = commands
    struct.pack_into("<III",buf,0x400,0x94000002,0xd503201f,0xd65f03c0)
    struct.pack_into("<i",buf,0x500,0x100)
    struct.pack_into("<Iii",buf,0x600,16,0,0x18)
    buf[0x620:0x62b] = b"WidgetCore\0"
    buf[0x680:0x688] = b"UIProbe\0"
    struct.pack_into("<IBBHQ",buf,0x700,1,0x0f,1,0,VM+0x400)
    buf[0x750:0x750+len(b"\0_$sWidgetCore\0")] = b"\0_$sWidgetCore\0"
    buf[0x810:0x813] = b"\x80\x08\x00"
    return bytes(buf)

class ReverseLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"SthenoTest.dylib"
        self.path.write_bytes(fixture())

    def test_arm64e_symbol_and_real_swift_type_descriptor(self):
        data = rev.analyze(self.path)
        self.assertEqual(data["slice_count"],1)
        item=data["slices"][0]
        self.assertEqual(item["architecture"],"arm64e")
        self.assertEqual(item["uuid"],b"0123456789abcdef".hex())
        self.assertEqual(item["swift_nominal_types"][0]["name"],"WidgetCore")
        self.assertEqual(item["swift_nominal_types"][0]["kind"],"class")
        self.assertEqual(item["objc_metadata"]["__objc_classname"]["strings"][0]["text"],"UIProbe")
        self.assertEqual(item["matching_symbols"][0]["name"],"_$sWidgetCore")
        self.assertEqual(item["function_starts"]["samples"],["0x1400"])
        self.assertFalse(item["encrypted"])

    def test_builtin_arm64_branch_target(self):
        result=rev.analyze(self.path,at=VM+0x400,count=2)["slices"][0]
        self.assertTrue(result["disassembler"] in ("capstone","builtin-branch-only"))
        self.assertTrue(any(x["mnemonic"]=="bl" for x in result["instructions"]))
        if result["disassembler"] == "builtin-branch-only":
            self.assertEqual(result["instructions"][0]["target"],"0x1408")

    def test_swift_search_filter(self):
        self.assertEqual(len(rev.analyze(self.path,search="Widget")["slices"][0]["swift_nominal_types"]),1)
        self.assertEqual(rev.analyze(self.path,search="missing")["slices"][0]["swift_nominal_types"],[])

    def test_arm64_not_falsely_arm64e(self):
        self.path.write_bytes(fixture(subtype=0))
        self.assertEqual(rev.analyze(self.path)["slices"][0]["architecture"],"arm64")

    def test_fat_macho_offset_and_bounds(self):
        thin=fixture()
        fat = struct.pack(">IIiiIII",0xcafebabe,1,rev.ARM64,2,0x100,len(thin),2)
        self.path.write_bytes(fat.ljust(0x100,b"\0")+thin)
        self.assertEqual(rev.analyze(self.path)["slices"][0]["architecture"],"arm64e")
        bad = struct.pack(">IIiiIII",0xcafebabe,1,rev.ARM64,2,0xffffff00,len(thin),2)
        self.path.write_bytes(bad.ljust(0x100,b"\0")+thin)
        with self.assertRaises(rev.ParseError): rev.analyze(self.path)

    def test_truncated_and_malformed_load_commands(self):
        self.path.write_bytes(fixture()[:50])
        with self.assertRaises(rev.ParseError): rev.analyze(self.path)
        buf = bytearray(fixture())
        struct.pack_into("<I",buf,32+4,0)
        self.path.write_bytes(buf)
        with self.assertRaises(rev.ParseError): rev.analyze(self.path)

    def test_output_is_not_allowed_to_clobber_input(self):
        proc=subprocess.run([sys.executable,str(Path(rev.__file__)),"analyze",str(self.path),
                             "--out",str(self.path)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,2)
        self.assertEqual(self.path.read_bytes(),fixture())

    def test_no_false_success_for_full_disassembly_without_capstone(self):
        proc=subprocess.run([sys.executable,str(Path(rev.__file__)),"doctor"],
                            capture_output=True,text=True)
        self.assertEqual(proc.returncode,0)
        self.assertFalse(json.loads(proc.stdout)["runtime_hooking"])

if __name__=="__main__":
    unittest.main()
