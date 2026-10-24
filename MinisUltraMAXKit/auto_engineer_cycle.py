#!/usr/bin/env python3
"""R5.5 foreground execution cycle: source patch -> tests -> checkpoint.

The AI model must inspect code and AUTHOR the diff via existing file/shell tools.
This runner actually applies that reviewed diff and executes discovered tests,
and produces a machine-readable next action. No model API, background daemon,
network calls, installs, pushes, or unattended resprings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import autopilot
import source_patch

MAX_CHECKS = 4


def safe_checkpoint(project, objective):
    # Do not log arbitrary project descriptions, file contents or credentials.
    key = hashlib.sha256(str(project).encode()).hexdigest()[:20]
    directory = autopilot.state_file(project).parent
    return directory / (key + ".engineer.json")


def run_cycle(project, objective, patch, expected_head, execute, approve_source_edit,
              allow_build, timeout):
    project = autopilot.valid_project(project)
    if not objective.strip():
        raise ValueError("NO-GO: development objective is required")
    state_path = safe_checkpoint(project, objective)
    summary = autopilot.git_summary(project)
    result = {
        "status": "needs_execution",
        "project": str(project),
        "objective_sha256": hashlib.sha256(objective.encode()).hexdigest(),
        "before_revision": summary["revision"],
        "source_edit": None,
        "checks": [],
        "release_ready": False,
        "device_verified": False,
    }
    if not execute:
        result["status"] = "plan_only"
        result["next_agent_action"] = "Use actual file tools to inspect code and produce an exact minimal diff; rerun with --execute."
        return result
    if patch is not None:
        if not approve_source_edit:
            result["status"] = "approval_required_for_source_edit"
            result["next_agent_action"] = "Source edits require --approve-source-edit; nothing changed."
            return result
        if not expected_head:
            result["status"] = "expected_head_required"
            result["next_agent_action"] = "Use exact current git rev-parse HEAD and retry; nothing changed."
            return result
        path = Path(patch).expanduser()
        project, file, revision, payload = source_patch.check_patch(project, path, expected_head)
        source_patch.git(project, "apply", "--whitespace=error", "-", input_bytes=payload)
        result["source_edit"] = {
            "status": "applied",
            "path": file,
            "patch_sha256": hashlib.sha256(payload).hexdigest(),
            "base_revision": revision,
        }
    steps = autopilot.choose_steps(project)
    selected = steps[:MAX_CHECKS]
    if not selected:
        result["status"] = "blocked_no_supported_runner"
        result["next_agent_action"] = (
            "Inspect existing project tests/build scripts and invoke the appropriate "
            "real tool, or add focused regression tests on a development branch. "
            "Do not repeat a general-purpose audit."
        )
    else:
        for name, argv in selected:
            if name == "theos-deb-build" and not allow_build:
                result["status"] = "approval_required_for_build"
                result["next_agent_action"] = "Build requires --allow-build after inspection of Makefile/control; existing code edits are retained."
                break
            completed = autopilot.execute(project, name, argv, timeout)
            result["checks"].append(completed)
            if completed["outcome"] != "pass":
                result["status"] = "needs_source_repair"
                result["next_agent_action"] = (
                    "Read the first causal error in the actual test output, "
                    "author one minimal source diff and run this cycle again. "
                    "Do not repeat unchanged retries."
                )
                break
        else:
            result["status"] = "verified_checks_passed"
            result["next_agent_action"] = (
                "Review git diff and coverage; compile/package with the existing "
                "toolchain and conduct real device acceptance before declaring delivery."
            )
    # Atomic persistence with permissions; save only sanitized bounded tool output.
    result["updated_at"] = autopilot.timestamp()
    result["checks"] = [{**x, "excerpt": autopilot.clean(x.get("excerpt", ""))}
                        for x in result["checks"]]
    autopilot.save_state(state_path, result)
    result["checkpoint_file"] = str(state_path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="R5.5 executable developer cycle")
    parser.add_argument("--project", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--patch-file")
    parser.add_argument("--expected-head")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approve-source-edit", action="store_true")
    parser.add_argument("--allow-build", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args(argv)
    if args.timeout < 1 or args.timeout > 300:
        parser.error("--timeout must be 1..300")
    try:
        report = run_cycle(args.project, args.objective, args.patch_file,
                           args.expected_head, args.execute,
                           args.approve_source_edit, args.allow_build, args.timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] in ("plan_only", "verified_checks_passed") else 1
    except (OSError, ValueError, source_patch.Denied) as error:
        print("NO-GO: " + autopilot.clean(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
