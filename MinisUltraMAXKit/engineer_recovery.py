#!/usr/bin/env python3
"""R5.6 Engineer Recovery: real provider-limit classification + durable safe handoff.

This program does not invoke an LLM, bypass quotas, choose paid endpoints, or
work after the application is closed. It preserves exact next actions so a
future user-authorized AI session can continue from verified work.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import autopilot
import auto_engineer_cycle as cycle

MAX_ERROR_CHARS=8192
def classify_http_error(error, status=None):
    """Status plus *specific* response text; never infer exhaustion from 429 alone."""
    raw=str(error or "")[:MAX_ERROR_CHARS].lower()
    try: status=int(status) if status is not None else None
    except (ValueError,TypeError): status=None
    if re.search(r"insufficient_quota|quota[_ -]?exceeded|billing[_ -]?hard[_ -]?limit|credit[s]? exhausted",raw):
        kind="quota_exhausted"
    elif re.search(r"invalid_api_key|incorrect.api.key|unauthorized|invalid.credentials",raw) or status==401:
        kind="authentication_denied"
    elif re.search(r"model[_ -]?not[_ -]?found|not supported when using codex|model is not available",raw):
        kind="model_unavailable"
    elif re.search(r"rate[_ -]?limit|too many requests|requests per minute|tokens per minute|try again later",raw) or status==429:
        kind="rate_limited"
    elif re.search(r"timeout|timed out|gateway timeout",raw) or status in (408,504):
        kind="transient_timeout"
    elif status in (500,502,503):
        kind="transient_server_error"
    elif status==403:
        kind="authorization_required"
    elif status==400:
        kind="request_rejected_unknown"
    else:
        kind="unknown_failure"
    advised={
        "quota_exhausted":"Stop model calls. A future user-authorized session or available provider quota is required. Execute reviewed local tests only.",
        "rate_limited":"Pause model calls. Use the provider's documented retry-after if available; do not fabricate a wake-up time.",
        "authentication_denied":"Do not retry or change credentials automatically; inspect provider settings with user consent.",
        "model_unavailable":"Do not silently switch providers or paid models; preserve state and check verified available models later.",
        "transient_timeout":"Preserve checkpoint; request a single bounded new attempt only when permitted.",
        "transient_server_error":"Preserve checkpoint; avoid automatic rapid retries.",
        "authorization_required":"User/provider authorization may be needed; no unauthorized retries.",
        "request_rejected_unknown":"Inspect sanitized response detail; HTTP 400 alone cannot identify the cause.",
        "unknown_failure":"Read sanitized failure details; do not infer provider quota or guess a fix."}
    return {"kind":kind,"safe_next_action":advised[kind],"automatic_model_retry":False}

def path_for(project):
    return autopilot.state_file(project).parent / (hashlib.sha256(str(project).encode()).hexdigest()[:20]+".provider.json")

def get_state(project):
    state_path=path_for(project)
    if state_path.is_symlink():
        raise ValueError("NO-GO: symlink provider state file")
    if not state_path.exists(): return None
    obj=json.loads(state_path.read_text(encoding="utf-8"))
    if obj.get("schema")!=1 or obj.get("project")!=str(project):
        raise ValueError("NO-GO: inconsistent provider checkpoint")
    return obj

def inspect(project, objective):
    project=autopilot.valid_project(project)
    existing=get_state(project)
    journal=cycle.safe_checkpoint(project,objective)
    if journal.is_symlink(): raise ValueError("NO-GO: linked engineer journal")
    data=json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else None
    if data and data.get("project")!=str(project): raise ValueError("NO-GO: mismatched engineer journal")
    objective_hash=hashlib.sha256(objective.encode()).hexdigest()
    if data and data.get("objective_sha256")!=objective_hash:
        data=None
    source=autopilot.source_fingerprint(project)
    saved=existing.get("source_fingerprint") if existing else None
    return {"project":str(project),"provider":existing.get("category") if existing else "unknown",
            "status":"checkpoint_found" if existing or data else "no_checkpoint",
            "engineer_stage":data.get("status") if data else None,
            "last_inflight_step":data.get("current_step") if data else None,
            "last_completed_checks":[{"step":x["step"],"outcome":x["outcome"]} for x in data.get("checks",[])] if data else [],
            "source_fingerprint":source,
            "source_modified_since_provider_checkpoint": bool(saved and source!=saved),
            "can_auto_retry_model":False,
            "can_resume_without_model":bool(data and data.get("status") in ("running_checks","source_applied_tests_pending","needs_source_repair")),
            "next_action":"Read the verified engineer checkpoint; resume only after source and test review. No background work or model quota bypass."}

def record(project, objective, status, error):
    project=autopilot.valid_project(project)
    report=classify_http_error(error,status)
    data={"schema":1,"project":str(project),"objective_sha256":hashlib.sha256(objective.encode()).hexdigest(),
          "category":report["kind"],"http_status":status if status is not None else None,
          "message_sha256":hashlib.sha256(error.encode()).hexdigest(),
          "recorded_at":autopilot.timestamp(),
          "source_fingerprint":autopilot.source_fingerprint(project),
          "engineer_checkpoint":str(cycle.safe_checkpoint(project,objective)),
          "safe_next_action":report["safe_next_action"],"automatic_model_retry":False}
    autopilot.save_state(path_for(project),data)
    return {"status":"provider_checkpoint_saved","category":data["category"],
            "safe_next_action":data["safe_next_action"],"automatic_model_retry":False,
            "checkpoint_file":str(path_for(project)),
            "note":"No API-key, raw response, prompt, credential, or conversation text is persisted."}

def local_resume(project,objective,expected_source,execute=False,reviewed=False):
    project=autopilot.valid_project(project)
    if not execute or not reviewed:
        return {"status":"approval_required","next_action":"Explicit --execute-tests --reviewed-source and matching --expected-source fingerprint are required"}
    if autopilot.source_fingerprint(project)!=expected_source:
        return {"status":"source_changed","next_action":"Review source changes and refresh fingerprint before allowing local tests"}
    report=cycle.run_cycle(str(project),objective,None,None,True,False,False,90)
    return {"status":report["status"],"checks":report.get("checks",[]),
            "checkpoint_file":report.get("checkpoint_file"),
            "next_action":report.get("next_agent_action"),
            "provider_model_calls":0,"device_verified":False}

def main(argv=None):
    parser=argparse.ArgumentParser(description="No-quota-bypass local engineer checkpoint and resume")
    sub=parser.add_subparsers(dest="action",required=True)
    for name in ("status","record-limit","resume-local"):
        p=sub.add_parser(name)
        p.add_argument("--project",required=True)
        p.add_argument("--objective",required=True)
        if name=="record-limit":
            p.add_argument("--error-file",required=True)
            p.add_argument("--http-status",type=int)
        elif name=="resume-local":
            p.add_argument("--expected-source",required=True)
            p.add_argument("--execute-tests",action="store_true")
            p.add_argument("--reviewed-source",action="store_true")
    a=parser.parse_args(argv)
    try:
        if a.action=="status": result=inspect(a.project,a.objective)
        elif a.action=="record-limit":
            path=Path(a.error_file).expanduser()
            if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_ERROR_CHARS:
                raise ValueError("NO-GO: error-file must be an ordinary small local file")
            error=path.read_text(encoding="utf-8",errors="replace")
            result=record(a.project,a.objective,a.http_status,error)
        else:
            result=local_resume(a.project,a.objective,a.expected_source,a.execute_tests,a.reviewed_source)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result["status"] not in ("source_changed","approval_required") else 2
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        print("NO-GO engineer recovery: "+autopilot.clean(exc),file=sys.stderr)
        return 2

if __name__=="__main__": raise SystemExit(main())
