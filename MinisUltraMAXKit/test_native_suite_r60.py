import importlib.util
import json
import pathlib
import plistlib
import sys
import tempfile
import unittest
import zipfile

HERE=pathlib.Path(__file__).parent
a=importlib.util.spec_from_file_location("minis_r60_suite",HERE/"native_suite_r60.py")
m=importlib.util.module_from_spec(a);a.loader.exec_module(m)

class NativeR60Test(unittest.TestCase):
    def ips(self,path,bug,body):
        path.write_text(json.dumps({"bug_type":bug,"app_name":"SpringBoard"})+"\n"+json.dumps(body))
    def test_panic_without_apelin(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"panic.ips"
            self.ips(p,"109",{"panicString":"backboardd failure","product":"iPhone"})
            r=m.triage(p)
            self.assertEqual(r["category"],"panic")
            self.assertFalse(r["requires_apelin"])
            self.assertIn("backboardd",r["panic"]["text"])
    def test_jetsam_not_called_crash(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"jetsam.ips"
            self.ips(p,"210",{"memoryStatus":{"pageSize":16384},"largestProcess":"SpringBoard",
                              "processes":[{"name":"SpringBoard","rpages":1000}]})
            r=m.triage(p)
            self.assertEqual(r["category"],"jetsam")
            self.assertEqual(r["memory"]["processes"][0]["resident_pages"],1000)
            self.assertNotIn("faulting_thread",r)
    def test_resource(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"resource.ips"
            self.ips(p,"288",{"reason":"excessive CPU","threads":[]})
            r=m.triage(p)
            self.assertEqual(r["category"],"resource")
    def test_invalid_and_missing_body(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"bad.ips"
            p.write_text("xyz")
            with self.assertRaises(m.NoGo):m.triage(p)
            p.write_text('{"bug_type":"309"}\n[]')
            with self.assertRaises(m.NoGo):m.triage(p)
    def test_sdk_inspection_is_readonly(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t)
            p=root/"iPhoneOS16.5.sdk"
            p.mkdir()
            (p/"SDKSettings.plist").write_bytes(plistlib.dumps({"Version":"16.5"}))
            r=m.doctor([root])
            self.assertEqual(r["sdk_inventory"][0]["version"],"16.5")
            self.assertFalse(r["abi_verified"])
            self.assertFalse(r["requires_apelin"])
    def minimal_ipa(self,path,with_bridge=False,bundle="com.openminis.devultramax.r60"):
        pref="Payload/Minis.app/"
        with zipfile.ZipFile(path,"w") as z:
            z.writestr(pref+"Info.plist",plistlib.dumps({"CFBundleIdentifier":bundle}))
            z.writestr(pref+"_CodeSignature/CodeResources",b"ad-hoc test signature metadata")
            z.writestr(pref+"default_mount/usr/local/bin/minis-native","shell")
            z.writestr(pref+"default_mount/usr/local/lib/minis-dev-ultra/native_suite.py","pass")
            z.writestr(pref+"default_mount/usr/local/lib/minis-dev-ultra/native_crash.py","pass")
            z.writestr(pref+"default_mount/usr/local/lib/minis-dev-ultra/native_diagnostics_LICENSE.txt","MIT")
            if with_bridge:
                z.writestr(pref+"default_mount/usr/local/bin/minis-apelin","old")
    def test_ipa_gate_valid_and_wrong_id(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"test.ipa"
            self.minimal_ipa(p)
            r=m.ipa_gate(p,"com.openminis.devultramax.r60")
            self.assertFalse(r["cryptographic_signature_validated"])
            self.assertTrue(r["apelin_bridge_absent"])
            with self.assertRaises(m.NoGo):m.ipa_gate(p,"com.openminis.app")
    def test_old_bridge_fails(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"test.ipa"
            self.minimal_ipa(p,with_bridge=True)
            with self.assertRaises(m.NoGo):m.ipa_gate(p)
    def test_zip_slip_fails(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)/"bad.ipa"
            with zipfile.ZipFile(p,"w") as z:z.writestr("../danger","x")
            with self.assertRaises(m.NoGo):m.ipa_gate(p)

if __name__=="__main__":unittest.main()
