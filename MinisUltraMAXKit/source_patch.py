#!/usr/bin/env python3
"""Apply one reviewed source-only patch in an existing non-stable Git branch.

The assistant must create the patch from real project files. This tool does not
invent diffs, run an LLM, install packages, commit, push, respring or work in the
background. No shell commands from the patch are executed.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

SOURCE_EXTENSIONS = {'.swift', '.mm', '.m', '.h', '.hpp', '.c', '.cc', '.cpp',
                     '.py', '.x', '.xm', '.rs', '.go', '.kt', '.java', '.js',
                     '.jsx', '.ts', '.tsx'}
MAX_PATCH_BYTES = 128 * 1024

class Denied(ValueError):
    pass

def git(project, *args, input_bytes=None):
    result = subprocess.run(['git', '-C', str(project), *args],
                            input=input_bytes, capture_output=True, timeout=15,
                            check=False)
    if result.returncode:
        raise Denied('NO-GO git ' + ' '.join(args[:2]) + ': exit ' + str(result.returncode))
    return result.stdout.decode('utf-8', 'replace').strip()

def check_patch(project, patch_file, expected_head):
    if project.is_symlink() or not project.is_dir():
        raise Denied('NO-GO: project must be a real directory')
    project = project.resolve(strict=True)
    if str(project) in ('/', '/tmp', str(Path.home())):
        raise Denied('NO-GO: dedicated project directory required')
    if git(project, 'rev-parse', '--show-toplevel') != str(project):
        raise Denied('NO-GO: project must be the Git repository root')
    branch = git(project, 'symbolic-ref', '--short', 'HEAD')
    if branch in ('main', 'master') or branch.lower().startswith(('release/', 'stable/')):
        raise Denied('NO-GO: create an isolated development branch first')
    head = git(project, 'rev-parse', 'HEAD')
    if head != expected_head:
        raise Denied('NO-GO: revision changed since patch was reviewed')
    if git(project, 'status', '--porcelain', '--untracked-files=no'):
        raise Denied('NO-GO: tracked source has uncommitted changes')
    if patch_file.is_symlink() or not patch_file.is_file():
        raise Denied('NO-GO: patch file missing or symlink')
    payload = patch_file.read_bytes()
    if not payload or len(payload) > MAX_PATCH_BYTES or b'\x00' in payload:
        raise Denied('NO-GO: malformed or oversized patch')
    try:
        source = payload.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise Denied('NO-GO: patch must be UTF-8') from exc
    headers = re.findall(r'^diff --git a/([^\n ]+) b/([^\n ]+)$', source, re.M)
    if len(headers) != 1 or headers[0][0] != headers[0][1]:
        raise Denied('NO-GO: exactly one existing source file may change')
    rel = PurePosixPath(headers[0][0])
    if rel.is_absolute() or '..' in rel.parts or rel.suffix.lower() not in SOURCE_EXTENSIONS:
        raise Denied('NO-GO: invalid source path')
    if any(line.startswith(('rename ', 'copy ', 'new file mode', 'deleted file mode',
                            'old mode', 'new mode', 'GIT binary patch', 'Binary files'))
           for line in source.splitlines()):
        raise Denied('NO-GO: mode changes, new files and binary patches prohibited')
    target = project.joinpath(*rel.parts)
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(project):
        raise Denied('NO-GO: target not a safe regular project file')
    git(project, 'ls-files', '--error-unmatch', '--', str(rel))
    git(project, 'apply', '--check', '--whitespace=error', '-', input_bytes=payload)
    return project, str(rel), head, payload

def main(argv=None):
    parser = argparse.ArgumentParser(description='Apply one evidence-reviewed Git patch to an isolated source branch')
    parser.add_argument('--project', required=True)
    parser.add_argument('--patch-file', required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--approve-source-edit', action='store_true')
    args = parser.parse_args(argv)
    if not args.approve_source_edit:
        print('NO-GO: explicit --approve-source-edit required', file=sys.stderr)
        return 2
    try:
        project, path, head, patch = check_patch(Path(args.project).expanduser(),
                                                  Path(args.patch_file).expanduser(), args.expected_head)
        git(project, 'apply', '--whitespace=error', '-', input_bytes=patch)
        print(json.dumps({'status': 'source_patch_applied', 'file': path,
                          'branch': git(project, 'symbolic-ref', '--short', 'HEAD'),
                          'base_revision': head, 'patch_sha256': hashlib.sha256(patch).hexdigest(),
                          'next_agent_action': 'Inspect git diff, run focused tests, then build in isolation; device acceptance is not verified.',
                          'boundary': 'No installation, publish, respring, credential or stable-branch operation'},
                          ensure_ascii=False))
        return 0
    except (Denied, OSError, subprocess.TimeoutExpired) as exc:
        print('NO-GO: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
