"""Negative and positive tests: Minis R5.9 offline IPS + Mach-O diagnosis."""
import importlib.util,json,pathlib,struct,tempfile,unittest,uuid
src=pathlib.Path(__file__).with_name('minis_native_crash_r59.py')
spec=importlib.util.spec_from_file_location('native_crash',src)
n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)
GOOD=uuid.UUID('abcd1234-5678-4abc-8def-0123456789ab')
BAD=uuid.UUID('9abc1234-5678-4abc-8def-0123456789ab')
def macho(uid,stripped=False):
    vm=0x100000000
    seg=struct.pack('<II16sQQQQiiII',0x19,72,b'__TEXT'+b'\0'*10,vm,0x1000,0,0x200,7,5,0,0)
    uc=struct.pack('<II',0x1b,24)+uid.bytes
    sy=struct.pack('<IIIIII',0x2,24,0x120,0 if stripped else 1,0x130,64)
    fs=struct.pack('<IIII',0x26,16,0x180,8)
    cmds=seg+uc+sy+fs
    head=struct.pack('<IiiIIIII',0xfeedfacf,0x100000c,2,6,4,len(cmds),0,0)
    data=bytearray(0x200)
    data[:len(head+cmds)]=head+cmds
    if not stripped:
        data[0x120:0x130]=struct.pack('<IBBHQ',1,0x0f,1,0,vm+0x40)
        data[0x130:0x139]=b'\0_funcA\0\0'
    data[0x180:0x185]=b'\x40\x40\0\0\0'
    return bytes(data)
def ips(uid=GOOD,off=0x50,index=0):
    head={'bug_type':'309','app_name':'SpringBoard'}
    body={'procName':'SpringBoard','faultingThread':0,'exception':{'type':'EXC_BAD_ACCESS','signal':'SIGSEGV'},
      'threads':[{'triggered':True,'frames':[{'imageIndex':index,'imageOffset':off}]}],
      'usedImages':[{'name':'Stheno.dylib','uuid':str(uid),'base':0x100000000,'size':0x1000}]}
    return json.dumps(head)+'\n'+json.dumps(body)
class NativeDiagnosticsTest(unittest.TestCase):
    def test_uuid_matching_and_stripped_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            (d/'x.ips').write_text(ips())
            (d/'a.macho').write_bytes(macho(GOOD))
            r=n.analyze(d/'x.ips',[d/'a.macho'])
            self.assertEqual(r['frames'][0]['symbol'],'_funcA')
            self.assertEqual(r['frames'][0]['symbol_offset'],16)
            (d/'x.ips').write_text(ips(off=0x90))
            r=n.analyze(d/'x.ips',[d/'a.macho'])
            self.assertEqual(r['frames'][0]['symbol_status'],'UNKNOWN_OR_STRIPPED')
    def test_wrong_uuid_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            (d/'x.ips').write_text(ips())
            (d/'wrong.macho').write_bytes(macho(BAD))
            r=n.analyze(d/'x.ips',[d/'wrong.macho'])
            self.assertEqual(r['frames'][0]['symbol_status'],'NO_MATCHING_UUID')
            self.assertNotIn('symbol_offset',r['frames'][0])
    def test_bad_index_and_offset(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            p=d/'x.ips'
            p.write_text(ips(index=99));self.assertFalse(n.analyze(p,[])['frames'][0]['verified'])
            p.write_text(ips(off=0x10000));self.assertFalse(n.analyze(p,[])['frames'][0]['verified'])
    def test_truncated_macho_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            p=d/'truncated';p.write_bytes(macho(GOOD)[:80])
            with self.assertRaises(n.NotVerified):n.macho(p)
    def test_invalid_json_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            p=d/'bad.ips'
            p.write_text('bad\nnot-json')
            with self.assertRaises(n.NotVerified):n.ips(p)
            p.write_text(ips().replace('"imageOffset": 80','"imageOffset": -1'))
            with self.assertRaises(n.NotVerified):n.ips(p)
            p.write_text(json.dumps({'bug_type':'309'}))
            with self.assertRaises(n.NotVerified):n.ips(p)
if __name__=='__main__':unittest.main()
