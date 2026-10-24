#!/usr/bin/env python3
"""Evidence-gated reverse-analysis -> real isolated Objective-C Logos Hook project.

This creates actual editable Theos source by invoking the existing HookLab.
It is NOT an ABI verifier, Swift Hook generator, installer, respringer or
runtime success claim. Target and exact method signature require independent
evidence; missing evidence blocks generation without writing source.
"""
import argparse
import hashlib
import io
import json
import pathlib
import re
import sys
from types import SimpleNamespace

import devctl
import reverse_intake

MAX_EVIDENCE=128*1024
def sha256(path):
    result=hashlib.sha256()
    with pathlib.Path(path).open("rb") as file:
        for part in iter(lambda:file.read(1024*1024),b""):
            result.update(part)
    return result.hexdigest()

def verify_class(data, klass):
    collection=[]
    for slice_ in data.get("slices",data.get("analysis",{}).get("slices",[])):
        names=slice_.get("objc_metadata",{}).get("__objc_classname",{}).get("strings",[])
        if any(row["text"]==klass for row in names):
            collection.append({"architecture":slice_["architecture"],
                "slice_file_offset":slice_.get("slice_file_offset",0),
                "class_string":klass})
    return collection

def prepare(args):
    binary=pathlib.Path(args.binary).expanduser()
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("NO-GO: supplied binary must be real file")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",args.class_name):
        raise ValueError("NO-GO: Objective-C class name malformed")
    want_hash=args.expected_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}",want_hash) or sha256(binary)!=want_hash:
        raise ValueError("NO-GO: binary hash disagrees with inspected artifact")
    evidence=pathlib.Path(args.method_evidence).expanduser()
    if evidence.is_symlink() or not evidence.is_file() or evidence.stat().st_size>MAX_EVIDENCE:
        raise ValueError("NO-GO: exact method evidence is missing or oversized")
    proof=evidence.read_text("utf-8",errors="replace")
    # At minimum, the user provided evidence of the class AND entire
    # Objective-C declaration, never a guessed method from a Swift symbol.
    if not re.search(r"(?m)^Class:\s*"+re.escape(args.class_name)+r"\s*$",proof):
        raise ValueError("NO-GO: class not bound to provided signature evidence")
    if not any(line.strip()==args.method.strip() for line in proof.splitlines()):
        raise ValueError("NO-GO: verified method declaration missing from evidence file")
    result=reverse_intake.inspect(binary,args.member,args.class_name)
    names=verify_class(result,args.class_name)
    if not names:
        raise ValueError("NO-GO: no matching Objective-C class-name section evidence in selected binary")
    if not any(row["architecture"] in ("arm64","arm64e") for row in names):
        raise ValueError("NO-GO: class not evidenced in ARM64/arm64e slice")
    target=pathlib.Path(args.output).expanduser()
    if target.exists() or target.is_symlink():
        raise ValueError("NO-GO: new Hook project destination already exists")
    return {"binary_sha256":want_hash,"selected_member":args.member,
            "class_evidence":names,"signature_evidence_sha256":sha256(evidence),
            "method":args.method.strip(),"process":args.process,
            "kind":"Objective-C pass-through","ABI_verified":False,"PAC_verified":False,
            "device_verified":False,"status":"STATIC_PRECHECK_ONLY"}

def scaffold(args,proof):
    if not args.approve_scaffold:
        return {"status":"approval_required_for_new_source","preflight":proof,
                "next_action":"Approve creation of a pass-through test Hook project only after reviewing exact class and method evidence"}
    flags=SimpleNamespace(name=args.name,bundle_id=args.bundle_id,
                          process=args.process,class_name=args.class_name,
                          method=args.method,scheme=args.scheme,path=args.output,out=None)
    devctl.cmd_hook(flags)
    dest=pathlib.Path(args.output).expanduser()
    report=dest/"reverse-evidence.json"
    if report.exists() or report.is_symlink():
        raise ValueError("NO-GO: audit collision")
    report.write_text(json.dumps(proof,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {"status":"ISOLATED_PASS_THROUGH_SOURCE_CREATED","project":str(dest),
            "evidence_file":str(report),"source_exists":(dest/"Tweak.xm").is_file(),
            "build_verified":False,"device_verified":False,
            "next_action":"Review source/prototypes, run targeted static/build tests; only consider install after independent ABI/runtime validation."}

def main(argv=None):
    p=argparse.ArgumentParser(description="Generate real HookLab source from exact static/runtime evidence only")
    p.add_argument("--binary",required=True)
    p.add_argument("--member",help="Exact IPA/DEB member when needed")
    p.add_argument("--expected-sha256",required=True)
    p.add_argument("--method-evidence",required=True)
    p.add_argument("--class-name",required=True)
    p.add_argument("--method",required=True)
    p.add_argument("--name",required=True)
    p.add_argument("--bundle-id",required=True)
    p.add_argument("--process",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--scheme",choices=("roothide","rootless"),required=True)
    p.add_argument("--approve-scaffold",action="store_true")
    args=p.parse_args(argv)
    try:
        proof=prepare(args)
        result=scaffold(args,proof)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result["status"]=="ISOLATED_PASS_THROUGH_SOURCE_CREATED" else 3
    except (OSError,ValueError,reverse_intake.IntakeError,devctl.struct.error) as error:
        print("NO-GO reverse Hook bridge: "+str(error),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
