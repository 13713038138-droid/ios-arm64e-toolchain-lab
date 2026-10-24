"""Prove the R5.5 source editor applies an actual patch and rejects unsafe writes."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import source_patch

class SourcePatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.root)], check=True)
        self.command('config', 'user.name', 'Test Runner')
        self.command('config', 'user.email', 'runner@example.invalid')
        (self.root / 'Core.mm').write_text('int value = 1;\n')
        self.command('add', 'Core.mm')
        self.command('commit', '-qm', 'baseline')
        self.command('switch', '-qc', 'minis-auto/test')
        self.head = self.command('rev-parse', 'HEAD').stdout.strip()
        self.patch = Path(self.temp.name) / 'fix.patch'
        self.patch.write_text('diff --git a/Core.mm b/Core.mm\n--- a/Core.mm\n+++ b/Core.mm\n@@ -1 +1 @@\n-int value = 1;\n+int value = 2;\n')

    def command(self, *argv):
        return subprocess.run(['git', '-C', str(self.root), *argv], check=True,
                              capture_output=True, text=True)

    def invoke(self, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = source_patch.main(['--project', str(self.root), '--patch-file', str(self.patch),
                                      '--expected-head', self.head, '--approve-source-edit'])
        self.assertEqual(code, expected, err.getvalue())
        return out.getvalue(), err.getvalue()

    def test_real_patch_changes_only_target_file(self):
        out, _ = self.invoke()
        self.assertEqual(json.loads(out)['status'], 'source_patch_applied')
        self.assertEqual((self.root / 'Core.mm').read_text(), 'int value = 2;\n')
        self.assertIn('Core.mm', self.command('diff', '--name-only').stdout)

    def test_no_stable_branch_edit(self):
        self.command('switch', '-q', 'main')
        _, err = self.invoke(expected=2)
        self.assertIn('isolated development branch', err)
        self.assertEqual((self.root / 'Core.mm').read_text(), 'int value = 1;\n')

    def test_stale_revision_rejected(self):
        self.head = '0' * 40
        _, err = self.invoke(expected=2)
        self.assertIn('revision changed', err)
        self.assertEqual((self.root / 'Core.mm').read_text(), 'int value = 1;\n')

    def test_non_source_patch_rejected(self):
        self.patch.write_text(self.patch.read_text().replace('Core.mm', 'credentials.txt'))
        _, err = self.invoke(expected=2)
        self.assertIn('invalid source path', err)

    def test_symlink_patch_rejected(self):
        alias = Path(self.temp.name) / 'symlink.patch'
        alias.symlink_to(self.patch)
        self.patch = alias
        _, err = self.invoke(expected=2)
        self.assertIn('symlink', err)

    def test_no_approval_refuses(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = source_patch.main(['--project', str(self.root), '--patch-file', str(self.patch),
                                      '--expected-head', self.head])
        self.assertEqual(code, 2)
        self.assertEqual((self.root / 'Core.mm').read_text(), 'int value = 1;\n')

if __name__ == '__main__':
    unittest.main()
