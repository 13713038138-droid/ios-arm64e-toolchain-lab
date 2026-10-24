"""Real bounded multi-round source repair using a fake local model protocol."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import engineer_agent_loop as loop


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.state = root / "state"
        original = os.environ.get("MINIS_DEV_ULTRA_STATE")
        os.environ["MINIS_DEV_ULTRA_STATE"] = str(self.state)
        self.addCleanup(lambda: os.environ.pop("MINIS_DEV_ULTRA_STATE", None)
                        if original is None else os.environ.__setitem__("MINIS_DEV_ULTRA_STATE", original))
        self.git("init", "-q", "-b", "main", str(self.project), in_project=False)
        self.git("config", "user.name", "Tester")
        self.git("config", "user.email", "test@example.invalid")
        (self.project / "module.py").write_text("VALUE=1\n")
        (self.project / "test_module.py").write_text(
            "import unittest, module\n"
            "class T(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(module.VALUE,2)\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.git("switch", "-qc", "engineer/proposals")
        self.agent = root / "agent.py"
        self.agent.write_text("#!/usr/bin/env python3\n"
                              "import json,sys\n"
                              "data=json.load(sys.stdin)\n"
                              "print(json.dumps({'patch': 'diff --git a/module.py b/module.py\\n"
                              "--- a/module.py\\n+++ b/module.py\\n@@ -1 +1 @@\\n"
                              "-VALUE=1\\n+VALUE=2\\n'}))\n")
        self.agent.chmod(0o755)

    def git(self, *args, in_project=True):
        return subprocess.run(["git", "-C", str(self.project), *args]
                              if in_project else ["git", *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def run_loop(self, **kwargs):
        options = {"project": self.project, "objective": "Fix test",
                   "bridge": str(self.agent), "execute": True,
                   "approved": True, "rounds": 2, "timeout": 25}
        options.update(kwargs)
        return loop.run(**options)

    def test_model_patch_real_tests_checkpoint_and_no_release_claim(self):
        out = self.run_loop()
        self.assertEqual(out["status"], "candidate_tests_passed", out)
        self.assertEqual(out["model_calls"], 1)
        self.assertEqual(out["changed_file"], "module.py")
        self.assertEqual((self.project / "module.py").read_text(), "VALUE=2\n")
        self.assertFalse(out["signed_ipa"])
        self.assertFalse(out["device_verified"])
        saved = json.loads(loop.journal_path(self.project.resolve(), "Fix test").read_text())
        self.assertEqual(saved["status"], "candidate_tests_passed")

    def test_model_integration_is_disabled_without_approval(self):
        out = self.run_loop(approved=False)
        self.assertEqual(out["status"], "plan_only")
        self.assertEqual(out["model_calls"], 0)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_failed_patch_is_reversed_then_identical_patch_blocked(self):
        self.agent.write_text(self.agent.read_text().replace("+VALUE=2", "+VALUE=3"))
        out = self.run_loop()
        self.assertEqual(out["status"], "blocked_repeat_proposal", out)
        self.assertEqual(out["model_calls"], 2)
        self.assertTrue(out["rounds"][0]["candidate_reverted"])
        self.assertEqual((self.project / "module.py").read_text(), "VALUE=1\n")
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=no"), "")

    def test_stable_branch_rejected_without_model_execution(self):
        self.git("switch", "main")
        with self.assertRaisesRegex(ValueError, "stable branch"):
            self.run_loop()
        self.assertEqual((self.project / "module.py").read_text(), "VALUE=1\n")

    def test_untrusted_bridge_side_effect_is_rejected(self):
        self.agent.write_text("#!/usr/bin/env python3\n"
                              "import json,sys,pathlib\n"
                              "data=json.load(sys.stdin)\n"
                              "pathlib.Path('module.py').write_text('VALUE=999\\n')\n"
                              "print(json.dumps({'patch':'irrelevant'}))\n")
        out = self.run_loop()
        self.assertEqual(out["status"], "blocked_bridge_modified_workspace")
        self.assertEqual((self.project / "module.py").read_text(), "VALUE=999\n")

    def test_missing_bridge_blocks_without_running_tests(self):
        out = self.run_loop(bridge=None)
        self.assertEqual(out["status"], "blocked_no_model_bridge")
        self.assertEqual(out["initial_checks"] if "initial_checks" in out else [], [])


if __name__ == "__main__":
    unittest.main()
