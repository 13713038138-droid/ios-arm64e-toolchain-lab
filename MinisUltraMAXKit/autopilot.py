#!/usr/bin/env python3
"""Minis R5.4 bounded autonomous development step runner.

This is an actual inspect/test execution tool, not a background daemon or an
AI code-editing agent. The chat agent may apply source patches using its
available authorized tools, then run this tool again for test feedback.
Never installs packages, edits project source, pushes or publishes.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SENSITIVE = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
]
MAX_TEXT = 3000
MAX_STEPS = 5
ALLOW_BUILD = False

def clean(value):
    value = str(value or "")
    for pat in SENSITIVE:
        value = pat.sub("[REDACTED]", value)
    return value[-MAX_TEXT:]

def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def valid_project(path):
    p = Path(path).expanduser()
    if p.is_symlink():
        raise ValueError("NO-GO: linked project paths are not accepted")
    p = p.resolve(strict=True)
    if not p.is_dir() or str(p) in ("/", "/var", "/tmp", str(Path.home())):
        raise ValueError("NO-GO: specify a dedicated project directory")
    return p

def state_file(project):
    base = Path(os.environ.get("MINIS_DEV_ULTRA_STATE", str(Path.home() / ".local/state/minis-dev-ultra"))).expanduser()
    if base.is_symlink():
        raise ValueError("NO-GO: linked state directory")
    key = hashlib.sha256(str(project).encode()).hexdigest()[:20]
    return base / "autopilot" / (key + ".json")

def save_state(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("NO-GO: linked state file")
    fd, temp = tempfile.mkstemp(prefix=".autopilot-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(obj, out, ensure_ascii=False, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise

def load_state(project):
    path = state_file(project)
    if path.is_symlink():
        raise ValueError("NO-GO: linked state file")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or data.get("project") != str(project):
            raise ValueError("NO-GO: inconsistent autopilot checkpoint")
        return data
    return {"schema": 1, "project": str(project), "created_at": timestamp(),
            "last_stage": "new", "attempts": {}, "history": []}

def git_summary(project):
    if not (project / ".git").exists() or not shutil.which("git"):
        return {"repository": False, "revision": None, "dirty": None}
    def query(argv):
        try:
            r = subprocess.run(["git", "-C", str(project)] + argv, capture_output=True,
                               timeout=8, text=True, check=False)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    revision = query(["rev-parse", "--short=12", "HEAD"])
    status = query(["status", "--porcelain", "--untracked-files=no"])
    return {"repository": True, "revision": revision,
            "dirty": bool(status) if status is not None else None}

def choose_steps(project):
    # Discovery reads only filenames, not private code, commands or credentials.
    # Explicit fixed argv, no shell, no automatically executing project scripts.
    steps = []
    if (project / "pyproject.toml").exists() or list(project.glob("test_*.py")) or (project / "tests").is_dir():
        py = shutil.which("python3") or shutil.which("python")
        if py:
            steps.append(("python-tests", [py, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"]))
    if (project / "Package.swift").exists() and shutil.which("swift"):
        steps.append(("swift-tests", ["swift", "test"]))
    if (project / "Cargo.toml").exists() and shutil.which("cargo"):
        steps.append(("rust-tests", ["cargo", "test", "--offline"]))
    if (project / "go.mod").exists() and shutil.which("go"):
        steps.append(("go-tests", ["go", "test", "./..."]))
    if (project / "Makefile").exists() and (project / "control").exists():
        # Never infer that an arbitrary makefile is safe. Build only after a
        # separate, explicit --allow-build flag; package installation excluded.
        if shutil.which("minis-deb"):
            steps.append(("theos-deb-build", ["minis-deb", "auto", "--project", str(project), "--arch", "auto"]))
    return steps

def execute(project, label, argv, timeout):
    env = os.environ.copy()
    env["GOPROXY"] = "off"  # Go tests should not silently fetch modules.
    try:
        # The tool never starts a shell. Project tests can execute project code;
        # callers must use --execute after inspecting the project.
        done = subprocess.run(argv, cwd=str(project), capture_output=True,
                              timeout=timeout, check=False, env=env)
        output = (done.stdout + b"\n" + done.stderr)[-8192:].decode("utf-8", "replace")
        return {"step": label, "outcome": "pass" if done.returncode == 0 else "failed",
                "exit_code": done.returncode, "excerpt": clean(output)}
    except subprocess.TimeoutExpired as exc:
        return {"step": label, "outcome": "timeout", "exit_code": None,
                "excerpt": clean((exc.stdout or b"")[-2048:].decode("utf-8", "replace")
                                 if isinstance(exc.stdout, bytes) else str(exc.stdout or ""))}
    except OSError as exc:
        return {"step": label, "outcome": "unavailable", "exit_code": None,
                "excerpt": clean(exc)}

def report(args):
    project = valid_project(args.project)
    state = load_state(project)
    steps = choose_steps(project)
    github = git_summary(project)
    result = {"project": str(project), "revision": github["revision"],
              "repository": github["repository"], "dirty": github["dirty"],
              "mode": "inspect-only" if args.command in ("plan", "status") or not args.execute else "execute",
              "planned_steps": [name for name, _ in steps],
              "executed": [], "checkpoint_file": str(state_file(project)),
              "previous_stage": state.get("last_stage"), "status": "planned",
              "boundary": "No source edits, installs, deletions, app signing, publication or background execution."}
    if args.command == "status":
        result["status"] = state.get("last_stage")
        result["recent_history"] = state.get("history", [])[-5:]
        return result
    if not args.execute:
        result["status"] = "requires_explicit_execute"
        result["next_agent_action"] = ("After examining this repository and obtaining authority to run project tests, "
                                       "call 'autopilot.py run --project PATH --execute'.")
        return result
    if not steps:
        result["status"] = "blocked_no_supported_runner"
        result["next_agent_action"] = "Inspect the existing build scripts and select a supported, explicitly authorized tool; do not invent a passing build."
    else:
        for label, argv in steps[:max(1, min(args.max_steps, MAX_STEPS))]:
            if label == "theos-deb-build" and not args.allow_build:
                result["status"] = "approval_required_for_package_build"
                result["next_agent_action"] = "Inspect the Makefile and package control, then obtain explicit build authorization before --allow-build."
                break
            completed = execute(project, label, argv, args.timeout)
            result["executed"].append(completed)
            signature = hashlib.sha256((label + completed["outcome"] + completed.get("excerpt", "")).encode()).hexdigest()
            attempt = state["attempts"].get(signature, 0) + 1
            state["attempts"][signature] = attempt
            if completed["outcome"] != "pass":
                result["status"] = "blocked_repeat_failure" if attempt >= 2 else "needs_source_repair"
                result["next_agent_action"] = (
                    "STOP identical retries; inspect the first causal error, patch the smallest reversible "
                    "source change with authorized editing tools, then rerun focused tests."
                    if attempt >= 2 else
                    "Inspect this redacted test failure, locate cause in source, make one minimal reversible "
                    "patch with authorized editing tools, then invoke this runner again."
                )
                break
        else:
            result["status"] = "verified_steps_passed"
            result["next_agent_action"] = ("All EXECUTED checks passed; assess remaining release gates and sign/verify "
                                           "an IPA or DEB only using existing authorized build tools. Never equate "
                                           "these checks with device acceptance.")
    state["last_stage"] = result["status"]
    state["updated_at"] = timestamp()
    state["history"] = (state.get("history", []) + [{"at": timestamp(), "revision": github["revision"],
        "status": result["status"], "steps": [
            {"step": q["step"], "outcome": q["outcome"], "exit_code": q["exit_code"]}
            for q in result["executed"]]}])[-25:]
    save_state(state_file(project), state)
    return result

def main(argv=None):
    p = argparse.ArgumentParser(description="R5.4 bounded engineer autopilot: plan, execute tests, checkpoint")
    sp = p.add_subparsers(dest="command", required=True)
    for cmd in ("plan", "run", "status"):
        q = sp.add_parser(cmd)
        q.add_argument("--project", required=True)
        q.add_argument("--execute", action="store_true", help="Opt in to running project tests/build commands")
        q.add_argument("--allow-build", action="store_true", help="Separately approve a Theos DEB build (never install)")
        q.add_argument("--timeout", type=int, default=90)
        q.add_argument("--max-steps", type=int, default=3)
    a = p.parse_args(argv)
    if a.command != "run":
        a.execute = False
    if a.timeout < 1 or a.timeout > 300:
        p.error("--timeout must be 1..300 seconds per command")
    try:
        print(json.dumps(report(a), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("NO-GO:", clean(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
