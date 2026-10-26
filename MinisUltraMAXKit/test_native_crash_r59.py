import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import uuid
p=pathlib.Path(__file__).with_name("native_crash_r59.py")
spec=importlib.util.spec_from_file_location("minis_native_crash",p)
n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)
IDENT=uuid.UUID("abcd1234-5678-4abc-8def-0123456789ab")
OTHER=uuid.UUID("9abc1234-5678-4abc-8def-0123456789ab")
def macho(uid,strip=False):
    vm=0x100000000
    seg=struct.pack("<II16sQQQQiiII",0x19,72,b"__TEXT"+b"\0"*10,vm,0x1000,0,0x200,7,5,0,0)
    ident=struct.pack("<II",0x1b,24)+uid.bytes
    sym=struct.pack("<IIIIII",0x2,24,0x120,0 if strip else 1,0x130,64)
    func=struct.pack("<IIII",0x26,16,0x180,8)
    cmds=seg+ident+sym+func
    header=struct.pack("<IiiIIIII",0xfeedfacf,0x100000c,2,6,4,len(cmds),0,0)
    data=bytearray(0x200);data[:len(header+cmds)]=header+cmds
    if not strip:
        data[0x120:0x130]=struct.pack("<IBBHQ",1,0xf,1,0,vm+0x40)
        data[0x130:0x138]=b"\0funcA\0\0"
    data[0x180:0x185]=b"\x40\x40\0\0\0"
    return bytes(data)
def ips(uid=IDENT,offset=0x50,bad_index=False):
    hdr={"bug_type":"309","app_name":"SpringBoard"}
    body={"procName":"SpringBoard","faultingThread":0,
          "usedImages":[{"name":"Stheno.dylib","uuid":str(uid),
                         "base":0x100000000,"size":0x1000}],
          "threads":[{"triggered":True,"frames":[{"imageIndex":55 if bad_index else 0,
                                                   "imageOffset":offset}]}]}
    return json.dumps(hdr)+"\n"+json.dumps(body)
class NativeCrashR59(unittest.TestCase):
    def test_matching_uuid_and_stripped_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/"sample.ips").write_text(ips())
            (root/"match").write_bytes(macho(IDENT))
            r=n.analyze(root/"sample.ips",[root/"match"])
            self.assertEqual(r["frames"][0]["symbol"],"funcA")
            self.assertEqual(r["symbolication"]["matched_frames"],1)
            (root/"sample.ips").write_text(ips(offset=0x90))
            r=n.analyze(root/"sample.ips",[root/"match"])
            self.assertEqual(r["frames"][0]["symbol_status"],"UNKNOWN_OR_STRIPPED")
    def test_wrong_uuid_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/"sample.ips").write_text(ips())
            (root/"wrong").write_bytes(macho(OTHER))
            r=n.analyze(root/"sample.ips",[root/"wrong"])
            self.assertEqual(r["frames"][0]["symbol_status"],"NO_MATCHING_UUID")
            self.assertNotIn("symbol",r["frames"][0])
    def test_invalid_frame_image_index(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/"sample.ips").write_text(ips(bad_index=True))
            r=n.analyze(root/"sample.ips",[])
            self.assertFalse(r["frames"][0]["verified"])
    def test_corrupt_macho_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"bad";p.write_bytes(macho(IDENT)[:75])
            with self.assertRaises(n.NotVerified):n.inspect_binary(p)
    def test_malformed_ips_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"bad.ips"
            p.write_text("not json\nnonsense")
            with self.assertRaises(n.NotVerified):n.report(p)
            p.write_text(json.dumps({"bug_type":"309"}))
            with self.assertRaises(n.NotVerified):n.report(p)
if __name__=="__main__":unittest.main()
