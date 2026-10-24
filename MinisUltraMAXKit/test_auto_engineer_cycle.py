"""Prove the R5.5 engineer cycle performs real source edits, tests and checkpoints."""
import json
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import auto_engineer_cycle

class EngineerCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        self.state = Path(self.temp.name) / "state"
        original = os.environ.get("MINIS_DEV_ULTRA_STATE")
        os.environ["MINIS_DEV_ULTRA_STATE"] = str(self.state)
        self.addCleanup(lambda: os.environ.pop("MINIS_DEV_ULTRA_STATE", None)
                        if original is None else os.environ.__setitem__("MINIS_DEV_ULTRA_STATE", original))
        self.git("init", "-q", "-b", "main", str(self.project), in_project=False)
        self.git("config", "user.name", "Test Runner")
        self.git("config", "user.email", "runner@example.invalid")
        (self.project / "module.py").write_text("VALUE = 1\n")
        (self.project / "test_module.py").write_text(
            "import unittest, module\n"
            "class Checks(unittest.TestCase):\n"
            "    def test_value(self): self.assertEqual(module.VALUE, 2)\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.git("switch", "-qc", "engineer/fix")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.patch = Path(self.temp.name) / "change.diff"
        self.patch.write_text(
            "diff --git a/module.py b/module.py\n"
            "--- a/module.py\n+++ b/module.py\n"
            "@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n")

    def git(self, *args, in_project=True):
        command = ["git", "-C", str(self.project), *args] if in_project else ["git", *args]
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout

    def cycle(self, **kwargs):
        options = dict(project=str(self.project), objective="Fix broken test",
                       patch=None, expected_head=None, execute=True,
                       approve_source_edit=False, allow_build=False, timeout=20)
        options.update(kwargs)
        return auto_engineer_cycle.run_cycle(**options)

    def test_plan_does_not_modify_source(self):
        out = self.cycle(execute=False, patch=str(self.patch))
        self.assertEqual(out["status"], "plan_only")
        self.assertEqual((self.project / "module.py").read_text(), "VALUE = 1\n")
        self.assertFalse(self.state.exists())

    def test_patch_then_real_test_then_checkpoint(self):
        out = self.cycle(patch=str(self.patch), expected_head=self.head, approve_source_edit=True)
        self.assertEqual(out["status"], "verified_checks_passed")
        self.assertEqual(out["source_edit"]["path"], "module.py")
        self.assertEqual(out["checks"][0]["outcome"], "pass")
        self.assertEqual((self.project / "module.py").read_text(), "VALUE = 2\n")
        state = json.loads(Path(out["checkpoint_file"]).read_text())
        self.assertEqual(state["status"], "verified_checks_passed")
        self.assertFalse(state["device_verified"])

    def test_failing_tests_report_needs_repair(self):
        out = self.cycle()
        self.assertEqual(out["status"], "needs_source_repair")
        self.assertEqual(out["checks"][0]["outcome"], "failed")
        self.assertEqual((self.project / "module.py").read_text(), "VALUE = 1\n")

    def test_repeated_identical_failure_blocks_extra_test_execution(self):
        first = self.cycle()
        self.assertEqual(first["status"], "needs_source_repair")
        second = self.cycle()
        self.assertEqual(second["status"], "blocked_repeat_failure")
        self.assertEqual(second["checks"], [])
        self.assertEqual((self.project / "module.py").read_text(), "VALUE = 1\n")

    def test_dirty_branch_repeated_failure_is_not_rerun(self):
        # An edited source file makes Git dirty, but the same failed test should
        # never run again until the actual source or runner changes.
        (self.project / "module.py").write_text("VALUE = 3\n")
        first = self.cycle()
        self.assertEqual(first["status"], "needs_source_repair")
        second = self.cycle()
        self.assertEqual(second["status"], "blocked_repeat_failure")
        self.assertEqual(second["checks"], [])
        self.assertEqual(first["source_signature"], second["source_signature"])
        (self.project / "module.py").write_text("VALUE = 2\n")
        third = self.cycle()
        self.assertEqual(third["status"], "verified_checks_passed")
        self.assertNotEqual(third["source_signature"], second["source_signature"])

    def test_source_edit_requires_approval(self):
        out = self.cycle(patch=str(self.patch), expected_head=self.head)
        self.assertEqual(out["status"], "approval_required_for_source_edit")
        self.assertEqual((self.project / "module.py").read_text(), "VALUE = 1\n")

    def test_blocks_stale_head_without_partial_patch(self):
        with self.assertRaises(ValueError):
            self.cycle(patch=str(self.patch), expected_head="0" * 40, approve_source_edit=True)
        self.assertEqual((self.project / "module.py").read_text(), "VALUE = 1\n")

    def test_no_supported_test_is_not_a_fake_pass(self):
        (self.project / "test_module.py").unlink()
        # Cannot commit because this test doesn't supply a patch.
        out = self.cycle()
        self.assertEqual(out["status"], "blocked_no_supported_runner")
        self.assertEqual(out["checks"], [])

if __name__ == "__main__":
    unittest.main()
