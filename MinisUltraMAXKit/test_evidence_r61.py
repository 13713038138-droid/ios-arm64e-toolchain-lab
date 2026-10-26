"""R61: verify real bounded evidence-driven patch loop and negative gates."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import breakthrough_engine as evidence
import auto_engineer_cycle as cycle
import engineer_agent_loop as loop

DIFF='''diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
'''

def git(where,*args):
    return subprocess.run(["git",*args],cwd=str(where),check=True,capture_output=True,text=True).stdout.strip()

class EvidenceRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.project=Path(self.tmp.name)/"repo";self.project.mkdir()
        git(self.project,"init","-b","dev/evidence")
        git(self.project,"config","user.name","Tester")
        git(self.project,"config","user.email","tests@example.com")
        (self.project/"calc.py").write_text("def add(a, b):\n    return a - b\n")
        (self.project/"test_calc.py").write_text(
            "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n"
            "    def test_sum(self):\n        self.assertEqual(add(2,3),5)\n")
        git(self.project,"add","calc.py","test_calc.py")
        git(self.project,"commit","-m","init")
        self.ctx=patch.dict(os.environ,{"MINIS_DEV_ULTRA_STATE":str(Path(self.tmp.name)/"state")})
        self.ctx.start()
    def tearDown(self):
        self.ctx.stop();self.tmp.cleanup()
    def bridge(self,logic):
        path=Path(self.tmp.name)/"test_bridge.py"
        path.write_text("#!/usr/bin/env python3\nimport json,sys\nr=json.load(sys.stdin)\n"
                        "proposal="+repr(DIFF)+"\nprint(json.dumps("+logic+"))\n")
        path.chmod(0o755)
        return str(path)
    def test_real_failure_classification(self):
        r=cycle.run_cycle(str(self.project),"repair arithmetic",None,None,True,False,False,25)
        self.assertEqual(r["status"],"needs_source_repair")
        diagnosis=evidence.diagnose(r)
        self.assertTrue(diagnosis["has_actual_failure"])
        self.assertEqual(diagnosis["classification"],"behavior_regression")
        self.assertIn("assert",diagnosis["evidence"].lower())
    def test_identical_failure_preserves_evidence_no_rerun(self):
        a=cycle.run_cycle(str(self.project),"repair arithmetic",None,None,True,False,False,25)
        b=cycle.run_cycle(str(self.project),"repair arithmetic",None,None,True,False,False,25)
        self.assertEqual(b["status"],"blocked_repeat_failure")
        self.assertEqual(a["failure_key"],b["failure_key"])
        self.assertEqual(b["checks"],[])
        self.assertIsInstance(b["cached_failed_check"],dict)
    def test_source_context_and_symbol_search(self):
        a=evidence.probe(self.project,{"kind":"source_context","path":"calc.py","line":2})
        b=evidence.probe(self.project,{"kind":"find_symbol","symbol":"add"})
        self.assertIn("return a - b",a["content"])
        self.assertTrue(any(x["path"]=="calc.py" for x in b["matches"]))
    def test_probe_no_traversal_or_symlinks(self):
        with self.assertRaises(ValueError):
            evidence.probe(self.project,{"kind":"source_context","path":"../secret.py","line":1})
        with self.assertRaises(ValueError):
            evidence.probe(self.project,{"kind":"source_context","path":"/tmp/secret.py","line":1})
        (self.project/"link.py").symlink_to(self.project/"calc.py")
        with self.assertRaises(ValueError):
            evidence.probe(self.project,{"kind":"source_context","path":"link.py","line":1})
        (self.project/"keys.py").write_text("password = 'never send'\n")
        self.assertNotIn("never send",evidence.probe(self.project,{"kind":"source_context","path":"keys.py","line":1})["content"])
    def test_bridge_probe_then_real_patch_and_test(self):
        bridge=self.bridge('{"status":"need_probe","probe":{"kind":"find_symbol","symbol":"add"}} if "probe_result" not in r else {"patch":proposal}')
        result=loop.run(str(self.project),"repair arithmetic",bridge,execute=True,approved=True,rounds=1,timeout=25)
        self.assertEqual(result["status"],"candidate_tests_passed",result)
        self.assertEqual(result["model_calls"],2)
        self.assertEqual(len(result["probes"]),1)
        self.assertIn("return a + b",(self.project/"calc.py").read_text())
        self.assertFalse(result["device_verified"])
    def test_invalid_probe_fails_closed(self):
        bridge=self.bridge('{"status":"need_probe","probe":{"kind":"source_context","path":"../token.py","line":1}}')
        result=loop.run(str(self.project),"repair arithmetic",bridge,execute=True,approved=True,rounds=1,timeout=25)
        self.assertEqual(result["status"],"blocked_invalid_probe")
        self.assertIn("return a - b",(self.project/"calc.py").read_text())
    def test_probe_budget_caps_model_calls(self):
        bridge=self.bridge('{"status":"need_probe","probe":{"kind":"find_symbol","symbol":"add"}}')
        result=loop.run(str(self.project),"repair arithmetic",bridge,execute=True,approved=True,rounds=1,timeout=25)
        self.assertEqual(result["status"],"blocked_probe_budget")
        self.assertEqual(result["model_calls"],3)
    def test_no_approval_no_run(self):
        bridge=self.bridge('{"patch":proposal}')
        result=loop.run(str(self.project),"repair arithmetic",bridge,execute=True,approved=False,rounds=1,timeout=25)
        self.assertEqual(result["status"],"plan_only")
    def test_provider_error_stops_without_billing_loop(self):
        bridge=self.bridge('{"status":"provider_error","http_status":429,"error":"rate limited"}')
        result=loop.run(str(self.project),"repair arithmetic",bridge,execute=True,approved=True,rounds=1,timeout=25)
        self.assertEqual(result["status"],"blocked_provider")
        self.assertEqual(result["model_calls"],1)

if __name__=="__main__":unittest.main()
