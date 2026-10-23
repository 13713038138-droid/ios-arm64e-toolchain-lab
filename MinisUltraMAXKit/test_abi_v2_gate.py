#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("abi_v2_gate", HERE / "abi_v2_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.zip"
        self.candidate = self.root / "candidate.deb"
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("ExampleProject/Makefile", "TARGET = iphone:clang:16.5:16.0\n")
            archive.writestr(".github/workflows/abi.yml", "name: ABI verifier\n")
        self.candidate.write_bytes(b"SSH BUILD ONLY NOT APPLE VERIFIED")
        self.source_hash = gate.sha256_file(self.source)
        self.candidate_hash = gate.sha256_file(self.candidate)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_hashes_pass_preflight_but_not_abi_gate(self):
        report = gate.preflight(self.source, self.candidate, self.source_hash, self.candidate_hash)
        self.assertEqual(report["status"], "PREFLIGHT_PASS_NOT_APPLE_VERIFIED")
        self.assertFalse(report["apple_abi_v2_accepted"])
        self.assertEqual(report["candidate_deb"]["classification"], "SSH_BUILD_ONLY_NOT_APPLE_VERIFIED")
        self.assertEqual(report["source_zip"]["archive"]["entry_count"], 2)

    def test_source_hash_mismatch_is_no_go(self):
        report = gate.preflight(self.source, self.candidate, "0" * 64, self.candidate_hash)
        self.assertEqual(report["status"], "NO-GO")
        self.assertIn("source ZIP SHA-256 mismatch", report["errors"])

    def test_candidate_hash_mismatch_is_no_go(self):
        report = gate.preflight(self.source, self.candidate, self.source_hash, "0" * 64)
        self.assertEqual(report["status"], "NO-GO")
        self.assertIn("candidate DEB SHA-256 mismatch", report["errors"])
        self.assertFalse(report["apple_abi_v2_accepted"])

    def test_zip_path_traversal_is_rejected(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("../escape.txt", "not safe")
        report = gate.preflight(self.source, self.candidate, gate.sha256_file(self.source), self.candidate_hash)
        self.assertEqual(report["status"], "NO-GO")
        self.assertTrue(any("unsafe ZIP entry path" in error for error in report["errors"]))

    def test_report_refuses_to_overwrite_without_force(self):
        path = self.root / "report.json"
        path.write_text("keep me", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "report already exists"):
            gate.write_report({"status": "NO-GO"}, path, force=False)
        self.assertEqual(path.read_text(encoding="utf-8"), "keep me")


class AppleAccessTests(unittest.TestCase):
    def test_no_gh_fails_closed_without_network_or_dispatch(self):
        with patch.object(gate, "which", return_value=None):
            report = gate.apple_check()
        self.assertEqual(report["status"], "NO-GO")
        self.assertFalse(report["workflow_triggered"])
        self.assertFalse(report["source_uploaded"])
        self.assertIn("GitHub CLI", report["error"])

    def test_workflow_dispatch_input_parser(self):
        workflow = """name: R32 Apple ABI v2
on:
  workflow_dispatch:
    inputs:
      source_zip_path:
        description: Source archive in the checked-out private branch
        required: true
      clean_build:
        required: false
        default: 'true'
jobs:
  verify:
    steps:
      - run: clang -fptrauth-abi-version=2
      - run: python3 original_abi_verifier.py
"""
        parsed = gate.dispatch_input_names(workflow)
        self.assertTrue(parsed["supported"])
        self.assertEqual(parsed["inputs"], ["source_zip_path", "clean_build"])
        self.assertEqual(parsed["required_inputs"], ["source_zip_path"])

    def test_access_inspection_does_not_trigger_workflow(self):
        workflow = """name: R32 Apple ABI v2
on:
  workflow_dispatch:
    inputs:
      source_zip_path:
        required: true
jobs:
  verify:
    steps:
      - run: clang -fptrauth-abi-version=2
      - run: python3 original_abi_verifier.py
"""
        content = base64.b64encode(workflow.encode()).decode()
        def fake_api(_gh, endpoint, *extra):
            if endpoint == "repos/example-org/example-repo":
                return {"private": True, "default_branch": "main", "permissions": {"push": True}}
            if endpoint == "repos/example-org/example-repo/actions/runs/1":
                return {"id": 1, "status": "completed", "conclusion": "success",
                        "head_branch": "main", "head_sha": "abc123", "workflow_id": 12,
                        "html_url": "https://github.com/example-org/example-repo/actions/runs/1"}
            if endpoint == "repos/example-org/example-repo/actions/workflows/12":
                return {"id": 12, "name": "R32 Apple ABI v2", "path": ".github/workflows/abi.yml",
                        "state": "active", "html_url": "https://github.com/example-org/example-repo/actions"}
            if endpoint == "repos/example-org/example-repo/contents/.github/workflows/abi.yml":
                self.assertEqual(extra, ("-f", "ref=abc123"))
                return {"encoding": "base64", "content": content}
            raise AssertionError("unexpected GitHub API endpoint: " + endpoint)
        with patch.object(gate, "which", return_value="/fake/gh"), \
             patch.object(gate, "gh_json", side_effect=fake_api), \
             patch.object(gate.subprocess, "run", return_value=CompletedProcess(["gh"], 0, "", "")) as run:
            report = gate.apple_check()
        self.assertEqual(report["status"], "ACCESS_READY_REVIEW_REQUIRED")
        self.assertTrue(report["repository_private"])
        self.assertTrue(report["workflow"]["workflow_dispatch"])
        self.assertEqual(report["workflow"]["dispatch_inputs"], ["source_zip_path"])
        self.assertTrue(report["workflow"]["abi_markers_present"])
        self.assertTrue(report["workflow"]["verifier_markers_present"])
        self.assertFalse(report["workflow_triggered"])
        self.assertFalse(report["source_uploaded"])
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
