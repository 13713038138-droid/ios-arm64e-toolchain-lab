#!/usr/bin/env python3
"""Evidence-gated foreground model bridge -> actual source repair -> tests.

A configured, explicitly trusted executable supplies candidate unified diffs
through a JSON stdin/stdout protocol. The runner executes tests, validates
each candidate using source_patch, rolls failed candidates back, and keeps a
bounded checkpoint. It neither provides model credentials nor chooses models,
calls network APIs, installs, publishes, commits, or claims device acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import autopilot
import auto_engineer_cycle as cycle
import engineer_recovery
import source_patch

MAX_ROUNDS = 3
MAX_REPLY = 150 * 1024


def git(project, *args):
    return source_patch.git(project, *args)


def status(project):
    branch = git(project, "symbolic-ref", "--short", "HEAD")
    if branch in ("main", "master") or branch.lower().startswith(("stable/", "release/")):
        raise ValueError("NO-GO: model edit forbidden on stable branch")
    if git(project, "rev-parse", "--show-toplevel") != str(project):
        raise ValueError("NO-GO: project must be Git root")
    return {
        "head": git(project, "rev-parse", "HEAD"),
        "branch": branch,
        "tracked_dirty": bool(git(project, "status", "--porcelain", "--untracked-files=no")),
        "untracked": git(project, "ls-files", "--others", "--exclude-standard").splitlines(),
    }


def journal_path(project, objective):
    base = cycle.safe_checkpoint(project, objective)
    objective_hash = hashlib.sha256(objective.encode("utf-8")).hexdigest()[:16]
    return base.with_name(base.stem + "." + objective_hash + ".agent-loop.json")


def write_checkpoint(project, objective, report):
    report["updated_at"] = autopilot.timestamp()
    autopilot.save_state(journal_path(project, objective), report)


def call_bridge(executable, request, timeout, project):
    # No shell, provider fallback, hidden environment substitution, or prompt
    # execution. This process is itself trusted by explicit caller selection.
    done = subprocess.run(
        [str(executable)], input=json.dumps(request).encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        cwd=str(project), check=False,
    )
    if len(done.stdout) > MAX_REPLY:
        raise ValueError("NO-GO: model bridge response oversized")
    if done.returncode:
        return {"status": "bridge_failed", "error": autopilot.clean(
            done.stderr.decode("utf-8", "replace"))}
    try:
        data = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("NO-GO: model bridge did not return valid JSON")
    if not isinstance(data, dict):
        raise ValueError("NO-GO: model bridge response must be an object")
    return data


def run(project, objective, bridge, execute=False, approved=False,
        rounds=2, timeout=60):
    project = autopilot.valid_project(project)
    if not objective.strip():
        raise ValueError("NO-GO: objective required")
    before = status(project)
    report = {
        "status": "plan_only", "project": str(project), "branch": before["branch"],
        "baseline_head": before["head"], "rounds": [],
        "model_calls": 0, "device_verified": False, "signed_ipa": False,
        "release_ready": False,
    }
    if before["tracked_dirty"]:
        report["status"] = "blocked_dirty_baseline"
        return report
    if not execute or not approved:
        report["next_action"] = "Review the trusted model bridge and approve bounded source edits plus local tests."
        return report
    if not (1 <= rounds <= MAX_ROUNDS) or not (1 <= timeout <= 180):
        raise ValueError("NO-GO: bounded rounds 1..3 and timeout 1..180 required")
    if not bridge:
        report["status"] = "blocked_no_model_bridge"
        return report
    binary = Path(bridge).expanduser()
    if (not binary.is_absolute() or binary.is_symlink() or not binary.is_file()
            or not os.access(binary, os.X_OK)):
        report["status"] = "blocked_untrusted_or_missing_model_bridge"
        return report
    result = cycle.run_cycle(str(project), objective, None, None, True, False, False, timeout)
    report["initial_checks"] = [{k: x.get(k) for k in ("step", "outcome", "exit_code")}
                                for x in result.get("checks", [])]
    report["initial_stage"] = result["status"]
    if result["status"] == "verified_checks_passed":
        report["status"] = "candidate_tests_passed_no_edit"
        write_checkpoint(project, objective, report)
        return report
    if result["status"] not in ("needs_source_repair", "blocked_repeat_failure"):
        report["status"] = result["status"]
        write_checkpoint(project, objective, report)
        return report

    previous_patch = None
    for index in range(1, rounds + 1):
        if status(project) != before:
            report["status"] = "blocked_workspace_changed"
            break
        request = {
            "schema": 1, "action": "propose_single_file_patch",
            "project": str(project), "objective": objective,
            "baseline_head": before["head"], "attempt": index,
            "previous_patch_sha256": previous_patch,
            "test_status": result["status"],
            "test_excerpt": autopilot.clean(result.get("checks", [{}])[-1].get("excerpt", ""))
                            if result.get("checks") else "",
            "rules": "One existing source file; unified git diff; no commands, installs or credentials.",
        }
        try:
            reply = call_bridge(binary, request, timeout, project)
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            report["status"] = "blocked_model_bridge"
            report["bridge_error"] = autopilot.clean(str(exc))
            break
        report["model_calls"] += 1
        # A model adapter must not silently edit the project itself.
        if status(project) != before:
            report["status"] = "blocked_bridge_modified_workspace"
            break
        if reply.get("status") in ("provider_error", "bridge_failed"):
            message = str(reply.get("error", "provider error"))[:8192]
            code = reply.get("http_status")
            classified = engineer_recovery.record(project, objective, code, message)
            report["status"] = "blocked_provider"
            report["provider_category"] = classified["category"]
            break
        patch = reply.get("patch")
        if not isinstance(patch, str) or not patch or len(patch.encode("utf-8")) > source_patch.MAX_PATCH_BYTES:
            report["status"] = "blocked_missing_or_oversized_patch"
            break
        patch_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        if previous_patch == patch_sha:
            report["status"] = "blocked_repeat_proposal"
            break
        previous_patch = patch_sha
        with tempfile.TemporaryDirectory(prefix="minis-agent-review-") as temp:
            candidate = Path(temp) / "review.diff"
            candidate.write_text(patch, encoding="utf-8")
            try:
                source_patch.check_patch(project, candidate, before["head"])
            except (source_patch.Denied, OSError, ValueError) as exc:
                report["status"] = "blocked_invalid_patch"
                report["patch_error"] = autopilot.clean(str(exc))
                break
            write_checkpoint(project, objective, {**report, "status": "candidate_in_flight",
                             "current_round": index, "candidate_sha256": patch_sha})
            try:
                result = cycle.run_cycle(str(project), objective, str(candidate),
                                         before["head"], True, True, False, timeout)
            except (OSError, ValueError, source_patch.Denied) as exc:
                report["status"] = "blocked_patch_or_test_error"
                report["patch_error"] = autopilot.clean(str(exc))
                break
            item = {"attempt": index, "patch_sha256": patch_sha,
                    "test_status": result["status"],
                    "checks": [{k: x.get(k) for k in ("step", "outcome", "exit_code")}
                               for x in result.get("checks", [])]}
            report["rounds"].append(item)
            if result["status"] == "verified_checks_passed":
                report["status"] = "candidate_tests_passed"
                report["changed_file"] = result["source_edit"]["path"]
                write_checkpoint(project, objective, report)
                return report
            # Only roll back the exact approved candidate. Fail closed if a
            # test changed any other tracked files; never use git reset --hard.
            try:
                actual = git(project, "diff", "--name-only").splitlines()
                if actual != [result["source_edit"]["path"]]:
                    raise ValueError("Unexpected tracked edits during tests")
                git(project, "apply", "--reverse", "--check", str(candidate))
                git(project, "apply", "--reverse", str(candidate))
                if status(project) != before:
                    raise ValueError("Rollback did not restore baseline")
            except (ValueError, source_patch.Denied, OSError) as exc:
                report["status"] = "blocked_rollback_needs_review"
                report["rollback_error"] = autopilot.clean(str(exc))
                write_checkpoint(project, objective, report)
                return report
            item["candidate_reverted"] = True
            write_checkpoint(project, objective, {**report, "status": "failed_candidate_reverted"})
    else:
        report["status"] = "blocked_round_limit"
    write_checkpoint(project, objective, report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Bounded on-device AI bridge / source repair / test cycle")
    p.add_argument("--project", required=True)
    p.add_argument("--objective", required=True)
    p.add_argument("--model-bridge", help="Explicit trusted local executable: JSON stdin -> JSON patch stdout")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--approve-source-edit", action="store_true")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--timeout", type=int, default=60)
    a = p.parse_args(argv)
    try:
        out = run(a.project, a.objective, a.model_bridge, a.execute,
                  a.approve_source_edit, a.rounds, a.timeout)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["status"] in ("plan_only", "candidate_tests_passed",
                                     "candidate_tests_passed_no_edit") else 2
    except (OSError, ValueError, source_patch.Denied) as exc:
        print("NO-GO agent loop: " + autopilot.clean(str(exc)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
