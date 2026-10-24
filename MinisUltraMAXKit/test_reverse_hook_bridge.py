"""R5.6 ReverseLab -> HookLab real source-generation gate tests."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from test_reverse_lab import fixture
from test_reverse_intake import make_deb
import reverse_hook_bridge as bridge

class HookBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.binary=self.root/"Stheno.dylib"
        self.binary.write_bytes(fixture())
        self.hash=hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.evidence=self.root/"verified-method.txt"
        self.evidence.write_text("Class: UIProbe\n- (BOOL)isEnabled\n")
        self.output=self.root/"ProbeHook"
        self.opts={
            "binary":str(self.binary),"member":None,"expected_sha256":self.hash,
            "method_evidence":str(self.evidence),"class_name":"UIProbe",
            "method":"- (BOOL)isEnabled","name":"ProbeHook",
            "bundle_id":"com.example.probehook",
            "process":"com.openminis.devultramax.r55",
            "output":str(self.output),"scheme":"roothide",
            "approve_scaffold":False}

    def args(self,**changes):
        return SimpleNamespace(**{**self.opts,**changes})

    def test_existing_binary_no_approval_only_precheck(self):
        proof=bridge.prepare(self.args())
        self.assertEqual(proof["status"],"STATIC_PRECHECK_ONLY")
        self.assertFalse(proof["PAC_verified"])
        self.assertFalse(proof["device_verified"])
        info=bridge.scaffold(self.args(),proof)
        self.assertEqual(info["status"],"approval_required_for_new_source")
        self.assertFalse(self.output.exists())

    def test_success_creates_real_pass_through_root_hide_project(self):
        old_binary=self.binary.read_bytes()
        proof=bridge.prepare(self.args())
        result=bridge.scaffold(self.args(approve_scaffold=True),proof)
        self.assertEqual(result["status"],"ISOLATED_PASS_THROUGH_SOURCE_CREATED")
        self.assertTrue((self.output/"Tweak.xm").is_file())
        self.assertIn("%hook UIProbe",(self.output/"Tweak.xm").read_text())
        self.assertIn("return %orig;",(self.output/"Tweak.xm").read_text())
        makefile=(self.output/"Makefile").read_text()
        self.assertIn("ARCHS = arm64e",makefile)
        self.assertIn("THEOS_PACKAGE_SCHEME = roothide",makefile)
        audit=json.loads((self.output/"reverse-evidence.json").read_text())
        self.assertEqual(audit["binary_sha256"],self.hash)
        self.assertFalse(audit["ABI_verified"])
        self.assertEqual(self.binary.read_bytes(),old_binary)
        self.assertFalse((self.output/"packages").exists())
        self.assertFalse(result["build_verified"])

    def test_wrong_class_or_hash_or_unproven_signature_rejected(self):
        with self.assertRaises(ValueError):bridge.prepare(self.args(class_name="NonExistent"))
        with self.assertRaises(ValueError):bridge.prepare(self.args(expected_sha256="0"*64))
        self.evidence.write_text("Class: UIProbe\n- (BOOL)someOtherFunction\n")
        with self.assertRaises(ValueError):bridge.prepare(self.args())
        self.assertFalse(self.output.exists())

    def test_archive_target_is_explicit(self):
        deb=self.root/"Stheno.deb"
        member="./Library/MobileSubstrate/DynamicLibraries/Stheno.dylib"
        deb.write_bytes(make_deb(member,fixture()))
        digest=hashlib.sha256(deb.read_bytes()).hexdigest()
        proof=bridge.prepare(self.args(binary=str(deb),member=member,expected_sha256=digest))
        self.assertEqual(proof["selected_member"],member)
        self.assertTrue(proof["class_evidence"])
        with self.assertRaises(ValueError):
            bridge.prepare(self.args(binary=str(deb),member="./wrong.dylib",expected_sha256=digest))

    def test_existing_target_prevents_overwrite(self):
        self.output.mkdir()
        with self.assertRaises(ValueError):bridge.prepare(self.args())
        self.assertTrue(self.output.is_dir())

    def test_cli_is_one_json_response(self):
        command=[sys.executable,str(Path(bridge.__file__)),"--binary",str(self.binary),
            "--expected-sha256",self.hash,"--method-evidence",str(self.evidence),
            "--class-name","UIProbe","--method","- (BOOL)isEnabled","--name","ProbeHook",
            "--bundle-id","com.example.probehook","--process","com.openminis.devultramax.r55",
            "--output",str(self.output),"--scheme","roothide","--approve-scaffold"]
        proc=subprocess.run(command,capture_output=True,text=True,check=False)
        self.assertEqual(proc.returncode,0,proc.stderr)
        result=json.loads(proc.stdout)
        self.assertEqual(result["status"],"ISOLATED_PASS_THROUGH_SOURCE_CREATED")
        self.assertEqual(result["generator_status"],"CREATED_TEMPLATE_NOT_RUNTIME_VERIFIED")

if __name__=="__main__":
    unittest.main()
