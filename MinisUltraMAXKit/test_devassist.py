"""R5.3 offline checks: error class has specific, non-destructive next step."""
import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import devctl


class NonExpertAssistTests(unittest.TestCase):
    def test_backup_visible_but_codex_400_rejected(self):
        r = devctl.classify_development_error(
            'HTTP 400 {"detail":"The gpt-6.1-sol model is not supported when using Codex with a ChatGPT account."}'
        )
        self.assertEqual(r["category"], "codex_unavailable")
        self.assertFalse(r["can_fix_without_more_evidence"])
        self.assertFalse(r["category"] == "bad_reasoning")
        self.assertIn("备份", r["next_action"])

    def test_unknown_400_requires_error_detail(self):
        r = devctl.classify_development_error("出现 HTTP 400")
        self.assertEqual(r["category"], "generic_400")
        self.assertFalse(r["can_fix_without_more_evidence"])

    def test_bad_effort_has_narrow_fix(self):
        r = devctl.classify_development_error("400 Invalid reasoning_effort: ultra")
        self.assertEqual(r["category"], "bad_reasoning")
        self.assertTrue(r["can_fix_without_more_evidence"])
        self.assertIn("reasoning.effort", r["next_action"])

    def test_schema_and_build_errors_have_distinct_paths(self):
        self.assertEqual(devctl.classify_development_error("400 Unrecognized key prompt_cache_key")["category"], "bad_schema")
        self.assertEqual(devctl.classify_development_error("ld: undefined symbols: _sample")["category"], "build_failed")
        self.assertEqual(devctl.classify_development_error("iPhoneOS SDK missing")["category"], "missing_sdk")

    def test_no_evidence_does_not_claim_auto_success(self):
        r = devctl.classify_development_error("继续")
        self.assertEqual(r["category"], "need_evidence")
        self.assertFalse(r["can_fix_without_more_evidence"])

    def test_log_tail_is_bounded_and_error_body_not_echoed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "large.log"
            p.write_text("x" * 200000 + "\nHTTP 400, invalid reasoning_effort: ultra\nSECRET_THAT_SHOULD_NOT_ECHO\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                devctl.cmd_assist(argparse.Namespace(error="", log=str(p), stage="debug", out=None))
            obj = json.loads(out.getvalue())
            self.assertEqual(obj["category"], "bad_reasoning")
            self.assertEqual(obj["stage"], "debug")
            self.assertNotIn("SECRET_THAT_SHOULD_NOT_ECHO", out.getvalue())


if __name__ == "__main__":
    unittest.main()
