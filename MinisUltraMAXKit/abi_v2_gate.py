#!/usr/bin/env python3
"""Fail-closed R32 source preflight and Apple/Xcode CI access inspection.

This tool never edits the Apple CI repository and never dispatches a workflow.
It verifies supplied local inputs, then inspects the recorded private workflow
only when the current GitHub CLI session can read that repository.
"""
import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from urllib.parse import quote

DEFAULT_SOURCE_ZIP = "/var/minis/shared/example-project/r32/input/PROJECT_R32_SOURCE_UPLOAD.zip"
DEFAULT_CANDIDATE_DEB = "/var/minis/shared/example-project/r32/outputs/R32_SSH_BUILD_ONLY_NOT_APPLE_VERIFIED.deb"
DEFAULT_SOURCE_SHA256 = "081e7cea8f85c88de68f540adb98f4862f21de950db20e8219a90e765ee6ec33"
DEFAULT_CANDIDATE_SHA256 = "fdf8dd2fd50ec652bbd11942b23baa2d5fa0564be53a6251aba605e4fc1bd5eb"
DEFAULT_REPO = "example-org/example-repo"
DEFAULT_RUN_ID = 1
SYSTEM_BIN_DIRS = ["/var/jb/usr/bin", "/var/jb/bin", "/usr/local/bin", "/usr/bin", "/bin", "/opt/homebrew/bin"]
SECRET_PATTERNS = [
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b"),
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)[^\s]+"),
]


def which(name):
    found = shutil.which(name)
    if found:
        return found
    for directory in SYSTEM_BIN_DIRS:
        candidate = pathlib.Path(directory) / name
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def scrub(value):
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: (m.group(1) or "") + "[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text[:1200]


def sha256_file(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_zip(path):
    entries = []
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            name = info.filename
            candidate = pathlib.PurePosixPath(name)
            if candidate.is_absolute() or ".." in candidate.parts or "\x00" in name:
                raise ValueError("unsafe ZIP entry path: " + name[:180])
            if info.flag_bits & 0x1:
                raise ValueError("encrypted ZIP entries are not accepted")
            entries.append({
                "path": name,
                "size": info.file_size,
                "is_directory": info.is_dir(),
            })
    relevant = [
        item["path"] for item in entries
        if re.search(r"(?:abi|verif|workflow|r32|manifest|sha256)", item["path"], re.I)
    ]
    if not entries:
        raise ValueError("source ZIP contains no entries")
    return {"entry_count": len(entries), "entries": entries, "relevant_paths": relevant[:100]}


def write_report(report, out=None, force=False):
    if out:
        path = pathlib.Path(out).expanduser()
        if path.exists() and not force:
            raise ValueError("report already exists; choose another --out or pass --force")
        path.parent.mkdir(parents=True, exist_ok=True)
        report["report_path"] = str(path)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def preflight(source_zip=DEFAULT_SOURCE_ZIP, candidate_deb=DEFAULT_CANDIDATE_DEB,
              expected_source=DEFAULT_SOURCE_SHA256, expected_candidate=DEFAULT_CANDIDATE_SHA256):
    report = {
        "tool": "minis-abi",
        "status": "NO-GO",
        "source_zip": {"path": str(source_zip), "expected_sha256": expected_source},
        "candidate_deb": {
            "path": str(candidate_deb), "expected_sha256": expected_candidate,
            "classification": "SSH_BUILD_ONLY_NOT_APPLE_VERIFIED",
        },
        "apple_abi_v2_accepted": False,
        "note": "Input preflight is not an Apple/Xcode build and is not ABI-v2 acceptance.",
    }
    errors = []
    source = pathlib.Path(source_zip).expanduser()
    candidate = pathlib.Path(candidate_deb).expanduser()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_source or ""):
        errors.append("expected source SHA-256 must be 64 hexadecimal characters")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_candidate or ""):
        errors.append("expected candidate SHA-256 must be 64 hexadecimal characters")
    if not source.is_file():
        errors.append("source ZIP is missing: " + str(source))
    else:
        try:
            source_hash = sha256_file(source)
            report["source_zip"]["sha256"] = source_hash
            report["source_zip"]["sha256_matches"] = source_hash.lower() == expected_source.lower()
            if source_hash.lower() != expected_source.lower():
                errors.append("source ZIP SHA-256 mismatch")
            report["source_zip"]["archive"] = inspect_zip(source)
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            errors.append("source ZIP inspection failed: " + scrub(exc))
    if not candidate.is_file():
        errors.append("candidate DEB is missing: " + str(candidate))
    else:
        try:
            candidate_hash = sha256_file(candidate)
            report["candidate_deb"]["sha256"] = candidate_hash
            report["candidate_deb"]["sha256_matches"] = candidate_hash.lower() == expected_candidate.lower()
            if candidate_hash.lower() != expected_candidate.lower():
                errors.append("candidate DEB SHA-256 mismatch")
            dpkg_deb = which("dpkg-deb")
            if dpkg_deb:
                proc = subprocess.run(
                    [dpkg_deb, "-f", str(candidate), "Package", "Version", "Architecture"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15,
                )
                if proc.returncode == 0:
                    report["candidate_deb"]["control_fields"] = proc.stdout.splitlines()
                else:
                    report["candidate_deb"]["metadata_warning"] = scrub(proc.stderr or proc.stdout)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append("candidate DEB inspection failed: " + scrub(exc))
    report["errors"] = errors
    if not errors:
        report["status"] = "PREFLIGHT_PASS_NOT_APPLE_VERIFIED"
    return report


def run_capture(argv, timeout=30):
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(scrub(exc))
    if proc.returncode != 0:
        raise RuntimeError(scrub(proc.stderr or proc.stdout or ("command failed: " + " ".join(argv[:4]))))
    return proc.stdout


def gh_json(gh, endpoint, *extra_args):
    raw = run_capture([gh, "api", endpoint, *extra_args], timeout=45)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub API returned invalid JSON for " + endpoint + ": " + scrub(exc))


def dispatch_input_names(workflow_text):
    lines = workflow_text.splitlines()
    dispatch_at = None
    for i, line in enumerate(lines):
        if re.match(r"^  workflow_dispatch\s*:\s*(?:#.*)?$", line):
            dispatch_at = i + 1
            break
    if dispatch_at is None:
        return {"supported": False, "inputs": [], "required_inputs": []}
    block = []
    for line in lines[dispatch_at:]:
        if re.match(r"^  [A-Za-z_][A-Za-z0-9_-]*\s*:", line):
            break
        block.append(line)
    inputs_at = next((i for i, line in enumerate(block) if re.match(r"^    inputs\s*:", line)), None)
    if inputs_at is None:
        return {"supported": True, "inputs": [], "required_inputs": []}
    inputs = []
    required = []
    current = None
    for line in block[inputs_at + 1:]:
        match = re.match(r"^      ([A-Za-z_][A-Za-z0-9_-]*)\s*:", line)
        if match:
            current = match.group(1)
            inputs.append(current)
            continue
        if current and re.match(r"^        required\s*:\s*true\s*(?:#.*)?$", line):
            required.append(current)
    return {"supported": True, "inputs": inputs, "required_inputs": required}


def apple_check(repo=DEFAULT_REPO, run_id=DEFAULT_RUN_ID):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repo or "")):
        return {"tool": "minis-abi", "status": "NO-GO", "repository": str(repo),
                "workflow_triggered": False, "source_uploaded": False,
                "apple_abi_v2_accepted": False, "error": "repository must be owner/name"}
    if int(run_id) <= 0:
        return {"tool": "minis-abi", "status": "NO-GO", "repository": repo,
                "workflow_triggered": False, "source_uploaded": False,
                "apple_abi_v2_accepted": False, "error": "run ID must be positive"}
    report = {
        "tool": "minis-abi",
        "status": "NO-GO",
        "repository": repo,
        "reference_run_id": int(run_id),
        "workflow_triggered": False,
        "source_uploaded": False,
        "apple_abi_v2_accepted": False,
        "note": "Read-only access check only; no source push, workflow dispatch, or ABI-v2 pass is claimed.",
    }
    gh = which("gh")
    if not gh:
        report["error"] = "GitHub CLI (gh) is not installed; cannot inspect private Apple CI repository without credentials."
        return report
    try:
        auth = subprocess.run([gh, "auth", "status", "--hostname", "github.com"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        if auth.returncode != 0:
            report["error"] = "GitHub CLI is not authenticated for github.com: " + scrub(auth.stderr or auth.stdout)
            return report
        repo_data = gh_json(gh, "repos/" + repo)
        report["repository_private"] = bool(repo_data.get("private"))
        report["default_branch"] = repo_data.get("default_branch")
        report["write_access"] = (repo_data.get("permissions") or {}).get("push")
        run_data = gh_json(gh, "repos/{}/actions/runs/{}".format(repo, int(run_id)))
        report["reference_run"] = {
            "id": run_data.get("id"),
            "status": run_data.get("status"),
            "conclusion": run_data.get("conclusion"),
            "head_branch": run_data.get("head_branch"),
            "head_sha": run_data.get("head_sha"),
            "workflow_id": run_data.get("workflow_id"),
            "html_url": run_data.get("html_url"),
        }
        workflow_id = run_data.get("workflow_id")
        if not workflow_id:
            raise RuntimeError("reference run has no workflow_id")
        workflow = gh_json(gh, "repos/{}/actions/workflows/{}".format(repo, workflow_id))
        path = workflow.get("path")
        report["workflow"] = {
            "id": workflow_id,
            "name": workflow.get("name"),
            "path": path,
            "state": workflow.get("state"),
            "html_url": workflow.get("html_url"),
        }
        if not path:
            raise RuntimeError("could not resolve workflow path from the recorded run")
        ref = run_data.get("head_sha") or repo_data.get("default_branch")
        encoded_path = quote(path, safe="/")
        content_data = gh_json(gh, "repos/{}/contents/{}".format(repo, encoded_path), "-f", "ref=" + (ref or ""))
        if content_data.get("encoding") != "base64" or not content_data.get("content"):
            raise RuntimeError("workflow source content was not available as base64")
        workflow_text = base64.b64decode(content_data["content"]).decode("utf-8", errors="replace")
        dispatch = dispatch_input_names(workflow_text)
        report["workflow"]["workflow_dispatch"] = dispatch["supported"]
        report["workflow"]["dispatch_inputs"] = dispatch["inputs"]
        report["workflow"]["required_inputs"] = dispatch["required_inputs"]
        report["workflow"]["abi_markers_present"] = bool(re.search(
            r"fptrauth[-_ ]abi[-_ ]version.{0,16}2|abi[-_ ]v2|abi_v2|ABI\s+v2", workflow_text, re.I))
        report["workflow"]["verifier_markers_present"] = bool(re.search(
            r"verif|acceptance|gate", workflow_text, re.I))
        report["workflow"]["workflow_source_ref"] = ref
        report["status"] = "ACCESS_READY_REVIEW_REQUIRED"
        report["next_gate"] = (
            "Inspect the workflow's actual source input and original verifier. "
            "Stage the exact source ZIP on a private branch and dispatch only after those paths are confirmed."
        )
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        report["error"] = scrub(exc)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="R32 source-hash preflight and private Apple/Xcode CI access gate")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local tools; does not authenticate or trigger CI")
    pf = sub.add_parser("preflight", help="Verify exact R32 source ZIP and SSH build-only DEB hashes")
    pf.add_argument("--source-zip", default=DEFAULT_SOURCE_ZIP)
    pf.add_argument("--candidate-deb", default=DEFAULT_CANDIDATE_DEB)
    pf.add_argument("--expected-source-sha256", default=DEFAULT_SOURCE_SHA256)
    pf.add_argument("--expected-candidate-sha256", default=DEFAULT_CANDIDATE_SHA256)
    pf.add_argument("--out", default=None)
    pf.add_argument("--force", action="store_true")
    ac = sub.add_parser("apple-check", help="Read-only access and workflow inspection for the private Apple CI repo")
    ac.add_argument("--repo", default=DEFAULT_REPO)
    ac.add_argument("--run-id", type=int, default=DEFAULT_RUN_ID)
    ac.add_argument("--out", default=None)
    ac.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            tools = {name: which(name) for name in ("python3", "gh", "git", "dpkg-deb", "shasum", "unzip")}
            result = {
                "tool": "minis-abi",
                "status": "READY_FOR_PREFLIGHT" if tools["python3"] else "NO-GO",
                "tools": tools,
                "local_xcode_available": bool(which("xcodebuild") and which("xcrun")),
                "note": "Apple/Xcode ABI-v2 acceptance is performed by the authorized Apple CI workflow, not by the phone Clang 14 build.",
            }
            write_report(result)
            return 0 if tools["python3"] else 2
        if args.command == "preflight":
            result = preflight(args.source_zip, args.candidate_deb,
                               args.expected_source_sha256, args.expected_candidate_sha256)
            write_report(result, args.out, args.force)
            return 0 if result["status"] == "PREFLIGHT_PASS_NOT_APPLE_VERIFIED" else 2
        result = apple_check(args.repo, args.run_id)
        write_report(result, args.out, args.force)
        return 0 if result["status"] == "ACCESS_READY_REVIEW_REQUIRED" else 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"tool": "minis-abi", "status": "NO-GO", "error": scrub(exc)}, indent=2), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
