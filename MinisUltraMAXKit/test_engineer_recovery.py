"""Real recovery: limits, credential-safe state, explicit local test continuation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import engineer_recovery as recovery
import auto_engineer_cycle as cycle

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.project=self.root/"code"
        self.project.mkdir()
        self.state=self.root/"state"
        old=os.environ.get("MINIS_DEV_ULTRA_STATE")
        os.environ["MINIS_DEV_ULTRA_STATE"]=str(self.state)
        self.addCleanup(lambda: os.environ.pop("MINIS_DEV_ULTRA_STATE",None)
                        if old is None else os.environ.__setitem__("MINIS_DEV_ULTRA_STATE",old))
        (self.project/"module.py").write_text("VALUE=2\n")
        (self.project/"test_module.py").write_text("import unittest, module\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(module.VALUE,2)\n")
        self.objective="Correct unit tests"

    def test_server_limit_is_not_quota_claim(self):
        got=recovery.classify_http_error("Rate limited. Try again later",429)
        self.assertEqual(got["kind"],"rate_limited")
        self.assertFalse(got["automatic_model_retry"])
        self.assertNotEqual(got["kind"],"quota_exhausted")

    def test_specific_quota_only_when_response_says_so(self):
        self.assertEqual(recovery.classify_http_error("insufficient_quota",429)["kind"],"quota_exhausted")
        self.assertEqual(recovery.classify_http_error("HTTP 400",400)["kind"],"request_rejected_unknown")
        self.assertEqual(recovery.classify_http_error("model is not available",400)["kind"],"model_unavailable")
        self.assertEqual(recovery.classify_http_error("timeout",504)["kind"],"transient_timeout")

    def test_record_limit_keeps_no_raw_secret(self):
        secret="sk-"+("secretvalue"*10)
        result=recovery.record(self.project,self.objective,429,"rate limited "+secret)
        self.assertEqual(result["category"],"rate_limited")
        path=Path(result["checkpoint_file"])
        self.assertTrue(path.exists())
        self.assertNotIn(secret,path.read_text())
        self.assertNotIn("rate limited",path.read_text())
        saved=recovery.get_state(self.project.resolve())
        self.assertEqual(saved["schema"],1)
        self.assertFalse(saved["automatic_model_retry"])

    def test_readonly_status_no_exec(self):
        with patch("auto_engineer_cycle.autopilot.execute",side_effect=AssertionError("must not run")):
            state=recovery.inspect(self.project,self.objective)
        self.assertEqual(state["status"],"no_checkpoint")
        self.assertFalse(state["can_auto_retry_model"])
        self.assertFalse(self.state.exists())

    def test_real_local_tests_only_with_explicit_approval(self):
        import autopilot
        expected=autopilot.source_fingerprint(self.project)
        denied=recovery.local_resume(self.project,self.objective,expected,execute=False,reviewed=False)
        self.assertEqual(denied["status"],"approval_required")
        self.assertFalse(self.state.exists())
        okay=recovery.local_resume(self.project,self.objective,expected,execute=True,reviewed=True)
        self.assertEqual(okay["status"],"verified_checks_passed",okay)
        self.assertEqual(okay["checks"][0]["outcome"],"pass")
        self.assertEqual(okay["provider_model_calls"],0)
        self.assertFalse(okay["device_verified"])

    def test_source_changed_since_approval_blocks_tests(self):
        import autopilot
        expected=autopilot.source_fingerprint(self.project)
        (self.project/"module.py").write_text("VALUE=999 # tampered\n")
        with patch("auto_engineer_cycle.autopilot.execute",side_effect=AssertionError("unexpected execution")):
            result=recovery.local_resume(self.project,self.objective,expected,execute=True,reviewed=True)
        self.assertEqual(result["status"],"source_changed")

    def test_provider_checkpoint_captures_real_source_drift(self):
        recovery.record(self.project,self.objective,429,"rate limited")
        original=recovery.inspect(self.project,self.objective)
        self.assertFalse(original["source_modified_since_provider_checkpoint"])
        (self.project/"module.py").write_text("VALUE=999 # changed\n")
        altered=recovery.inspect(self.project,self.objective)
        self.assertTrue(altered["source_modified_since_provider_checkpoint"])

    def test_status_and_record_cli_without_private_output(self):
        program=Path(recovery.__file__)
        error=self.root/"error.txt"
        error.write_text("Rate limited; customer token sk-REDACT")
        cmd=["python3",str(program),"record-limit","--project",str(self.project),
             "--objective",self.objective,"--error-file",str(error),"--http-status","429"]
        p=subprocess.run(cmd,text=True,capture_output=True,check=False)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)["category"],"rate_limited")
        self.assertNotIn("sk-REDACT",p.stdout)
        q=subprocess.run(["python3",str(program),"status","--project",str(self.project),
                        "--objective",self.objective],text=True,capture_output=True)
        self.assertEqual(q.returncode,0,q.stderr)
        self.assertEqual(json.loads(q.stdout)["provider"],"rate_limited")

if __name__=="__main__":
    unittest.main()
