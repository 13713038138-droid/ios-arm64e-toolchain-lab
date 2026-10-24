"""R5.4 Auto Engineer executable regression and safety boundaries."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import autopilot

class AutoEngineerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "work" / "myproject"
        self.project.mkdir(parents=True)
        self.state = Path(self.tmp.name) / "state"
        old = os.environ.get("MINIS_DEV_ULTRA_STATE")
        os.environ["MINIS_DEV_ULTRA_STATE"] = str(self.state)
        self.addCleanup(lambda: os.environ.pop("MINIS_DEV_ULTRA_STATE", None)
                        if old is None else os.environ.__setitem__("MINIS_DEV_ULTRA_STATE", old))

    def invoke(self, *argv, expected=0):
        o,e=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(o),contextlib.redirect_stderr(e):
            rc=autopilot.main(list(argv))
        self.assertEqual(rc,expected,e.getvalue())
        return json.loads(o.getvalue()) if rc==0 else e.getvalue()

    def test_planning_never_runs_tests(self):
        (self.project/"test_unit.py").write_text("raise RuntimeError('would run if imported')\n")
        r=self.invoke("plan","--project",str(self.project))
        self.assertEqual(r["status"],"requires_explicit_execute")
        self.assertEqual(r["executed"],[])
        self.assertIn("python-tests",r["planned_steps"])
        self.assertFalse((self.state/"autopilot").exists())

    def test_executes_test_and_persists_checkpoint(self):
        (self.project/"test_ok.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_one(self): self.assertEqual(2,2)\n")
        r=self.invoke("run","--project",str(self.project),"--execute")
        self.assertEqual(r["status"],"verified_steps_passed")
        self.assertEqual(r["executed"][0]["outcome"],"pass")
        q=self.invoke("status","--project",str(self.project))
        self.assertEqual(q["status"],"verified_steps_passed")
        self.assertEqual(q["recent_history"][-1]["steps"][0]["outcome"],"pass")

    def test_repeated_failure_does_not_get_infinite_retry(self):
        (self.project/"test_bad.py").write_text("import unittest\nclass F(unittest.TestCase):\n def test_no(self): self.fail('failure seen')\n")
        x=self.invoke("run","--project",str(self.project),"--execute")
        self.assertEqual(x["status"],"needs_source_repair")
        y=self.invoke("run","--project",str(self.project),"--execute")
        self.assertEqual(y["status"],"blocked_repeat_failure")
        self.assertEqual(len(y["executed"]),1)

    def test_redacts_token_from_test_output_and_checkpoint(self):
        key="github_pat_"+"A"*27
        (self.project/"test_leak.py").write_text("import unittest\nclass F(unittest.TestCase):\n def test_no(self): self.fail('"+key+"')\n")
        r=self.invoke("run","--project",str(self.project),"--execute")
        self.assertNotIn(key,json.dumps(r))
        self.assertIn("[REDACTED]",r["executed"][0]["excerpt"])
        self.assertNotIn(key,autopilot.state_file(self.project.resolve()).read_text())

    def test_zero_tests_is_not_a_success(self):
        (self.project/"test_empty.py").write_text("VALUE=1\n")
        r=self.invoke("run","--project",str(self.project),"--execute")
        self.assertNotEqual(r["status"],"verified_steps_passed")
        self.assertEqual(r["executed"][0]["outcome"],"not_verified")

    def test_does_not_run_theos_without_separate_allow_build(self):
        (self.project/"Makefile").write_text("all:\n\t@echo no\n")
        (self.project/"control").write_text("Package: com.example.tweak\n")
        real=autopilot.shutil.which
        with patch.object(autopilot.shutil,"which",side_effect=lambda name: "/unused/minis-deb" if name=="minis-deb" else real(name)):
            r=self.invoke("run","--project",str(self.project),"--execute")
        self.assertEqual(r["status"],"approval_required_for_package_build")
        self.assertEqual(r["executed"],[])

    def test_excludes_project_symlink(self):
        alias=Path(self.tmp.name)/"link"
        alias.symlink_to(self.project,target_is_directory=True)
        err=self.invoke("run","--project",str(alias),"--execute",expected=2)
        self.assertIn("NO-GO",err)

    def test_fixed_commands_and_no_external_side_effects(self):
        (self.project/"test_ok.py").write_text("import unittest\nclass F(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n")
        steps=autopilot.choose_steps(self.project)
        self.assertTrue(steps)
        self.assertEqual(steps[0][1][1:],["-m","unittest","discover","-s",".","-p","test_*.py"])
        self.assertFalse(any("shell" in repr(s) or "sudo" in repr(s) for s in steps))

if __name__=="__main__":
    unittest.main()
