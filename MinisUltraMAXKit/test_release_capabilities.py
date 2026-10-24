"""Negative controls for R5.5->R5.6 source capability-retention gate."""
import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path
import release_capabilities as gate

class ParityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        all_rules={**gate.RULES,**gate.FULL_RULES}
        for file, needles in all_rules.values():
            target=self.root/file
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("a",encoding="utf-8") as out:
                for needle in needles: out.write(needle+"\n")

    def test_all_expected_r55_capabilities_and_r56_tooling_present(self):
        out=gate.evaluate(self.root,"core")
        self.assertEqual(out["status"],"PASS",out["failed"])
        self.assertGreaterEqual(out["checked"],17)
        self.assertFalse(out["device_verified"])
        self.assertFalse(out["network_login_verified"])

    def test_full_source_gate_requires_performance_and_skills(self):
        out=gate.evaluate(self.root,"full")
        self.assertEqual(out["status"],"PASS",out["failed"])
        p=self.root/gate.FULL_RULES["chat_scroll_performance"][0]
        p.write_text("invalid\n")
        self.assertEqual(gate.evaluate(self.root,"full")["status"],"NO-GO")
        self.assertEqual(gate.evaluate(self.root,"core")["status"],"PASS")

    def test_r56_isolated_group_does_not_implicitly_pass_r55(self):
        marker = self.root / gate.RULES["shared_group_id"][0]
        marker.write_text("group.com.openminis.devultramax.r56\n")
        with patch.dict(os.environ, {"MINIS_MAX_BUNDLE_ID": "com.openminis.devultramax.r56"}):
            self.assertEqual(gate.evaluate(self.root)["status"], "PASS")
        with patch.dict(os.environ, {"MINIS_MAX_BUNDLE_ID": "com.openminis.devultramax.r55"}):
            report = gate.evaluate(self.root)
            self.assertIn("shared_group_id", report["failed"])

    def test_missing_share_is_blocked(self):
        file=self.root/gate.RULES["share_extension_saved_record"][0]
        file.unlink()
        report=gate.evaluate(self.root)
        self.assertEqual(report["status"],"NO-GO")
        self.assertIn("share_extension_saved_record",report["failed"])

    def test_missing_reverse_search_is_blocked(self):
        file=self.root/gate.RULES["new_cross_package_reverse_executor"][0]
        file.write_text("def analyze_binary(): pass\n")
        report=gate.evaluate(self.root)
        self.assertIn("new_cross_package_reverse_executor",report["failed"])

    def test_symlink_rejected(self):
        target=self.root/gate.RULES["reverse_cli"][0]
        target.unlink()
        target.symlink_to(self.root/gate.RULES["original_macho_binary_inspector"][0])
        report=gate.evaluate(self.root)
        self.assertIn("reverse_cli",report["failed"])

if __name__=="__main__":unittest.main()
