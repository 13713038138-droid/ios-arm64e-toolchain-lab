#!/usr/bin/env python3
"""Minis R6.0 offline native developer suite (no Apelin app or privileged RPC).

Uses installed Minis' ReverseLab/CrashDoctor and adapts report-kind classification
from Apelin's MIT-licensed IPSDecoder (Copyright 2026 OwnGoal Studio).
See native_diagnostics_LICENSE.txt. Never installs, executes input code,
modifies device state, downloads, resprings, or claims unverified capability.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile

MAX_REPORT = 32*1024*1024
MAX_IPA = 1024*1024*1024
TOOLS = ("swiftc","clang","make","git","ldid","codesign","dpkg-deb",
         "llvm-objdump","llvm-dwarfdump","atos","python3")
ALLOWED_KINDS = {
    "109":"panic","210":"jetsam","288":"resource",
    "298":"hang","309":"crash","308":"crash","311":"crash"
}

class NoGo(ValueError):
    pass

def json_output(obj,output=None):
    raw=json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if output:
        with open(output,"x",encoding="utf-8") as f: f.write(raw)
    else:
        sys.stdout.write(raw)
    return obj

def read_limited(p,limit):
    p=Path(p)
    if not p.is_file() or p.stat().st_size>limit: raise NoGo("missing or oversized input")
    return p.read_bytes()

def safe_json(b):
    try:
        o=json.loads(b)
    except (UnicodeDecodeError,ValueError) as e: raise NoGo("invalid JSON document") from e
    if not isinstance(o,dict):raise NoGo("expected JSON object")
    return o

def kind_of(bug,body):
    if str(bug) in ALLOWED_KINDS: return ALLOWED_KINDS[str(bug)]
    if "memoryStatus" in body: return "jetsam"
    if "panicString" in body: return "panic"
    if "threads" in body and "usedImages" in body: return "crash_candidate"
    return "other"

def triage(path,binaries=()):
    raw=read_limited(path,MAX_REPORT)
    head,sep,bodydata=raw.partition(b"\n")
    if not sep: raise NoGo("Apple IPS header/body boundary missing")
    header=safe_json(head)
    body=safe_json(bodydata)
    category=kind_of(header.get("bug_type",""),body)
    result={"type":"apple_ips","category":category,
            "bug_type":str(header.get("bug_type",""))[:16],
            "process":str(body.get("procName") or header.get("app_name") or header.get("name") or "")[:160],
            "sha256":hashlib.sha256(raw).hexdigest(),
            "data_scope":"existing report; no live device access",
            "requires_apelin":False}
    if category in ("crash","crash_candidate"):
        import native_crash
        crash=native_crash.analyze(path,binaries)
        result.update({"faulting_thread":crash.get("faulting_thread"),
                       "exception":crash.get("exception"),
                       "frames":crash.get("frames",[])[:64],
                       "symbolication":crash.get("symbolication",{})})
    elif category=="jetsam":
        status=body.get("memoryStatus")
        status=status if isinstance(status,dict) else {}
        processes=body.get("processes")
        processes=processes if isinstance(processes,list) else []
        if len(processes)>10000:raise NoGo("oversized jetsam process list")
        result["memory"]={"page_size":status.get("pageSize"),"largest_process":body.get("largestProcess"),
                          "processes": [{"name":str(p.get("name",""))[:120],
                                         "resident_pages":p.get("rpages"),"reason":str(p.get("reason",""))[:120]}
                                        for p in processes[:12] if isinstance(p,dict)]}
    elif category=="panic":
        result["panic"]={"text":str(body.get("panicString",""))[:900],
                         "product":body.get("product"),"build":body.get("build")}
    elif category in ("hang","resource"):
        result["symptom"]={"event":str(body.get("event") or body.get("reason") or "")[:300],
                           "has_threads":isinstance(body.get("threads"),list)}
    else:
        result["reason"]="unsupported or analytics report; do not assert a crash"
    return result

def find_sdks(roots):
    found=[]
    for base in roots:
        folder=Path(base)
        if not folder.is_dir():continue
        for p in sorted(folder.glob("iPhoneOS*.sdk"))[:24]:
            try:
                if not p.is_dir() or p.is_symlink():continue
                info=p/"SDKSettings.plist"
                metadata=plistlib.loads(info.read_bytes()) if info.is_file() and info.stat().st_size<1000000 else {}
                found.append({"path":str(p),"version":str(metadata.get("Version","unknown")),
                              "platform":"iPhoneOS","verified_usable":False})
            except (OSError,ValueError):
                continue
    return found

def doctor(sdk_roots=()):
    tool_entries=[]
    for t in TOOLS:
        p=shutil.which(t)
        tool_entries.append({"name":t,"path":p,"found":bool(p),"tested":False})
    theos=Path(os.environ.get("THEOS","/var/mobile/theos"))
    paths=list(sdk_roots) if sdk_roots else [theos/"sdks",Path("/opt/theos/sdks"),
                                            Path("/var/mobile/theos/sdks"),
                                            Path("/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/SDKs")]
    return {"mode":"offline-read-only","requires_apelin":False,
            "theos":{"root":str(theos),"exists":theos.is_dir(),
                     "makefile_found":(theos/"makefiles/common.mk").is_file()},
            "sdk_inventory":find_sdks(paths),
            "tools":tool_entries,
            "abi_verified":False,"device_injection_verified":False,
            "notes":["Installed executable paths are evidence, not compiler compatibility proof",
                     "R5.9 ReverseLab/DEB tools remain available separately",
                     "No Apelin host CLI is installed or required by this suite"]}

def macho(path):
    import reverse_lab
    raw=reverse_lab.analyze(path)
    return {"tool":"existing_minis_reverse_lab","read_only":True,"requires_apelin":False,"result":raw}

def ipa_gate(path,expected_id=None):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>MAX_IPA:raise NoGo("missing or oversized IPA")
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    with zipfile.ZipFile(p,"r") as z:
        names=z.namelist()
        if len(names)>120000 or len(names)!=len(set(names)):raise NoGo("duplicate or oversized ZIP index")
        if any(x.startswith("/") or ".." in x.split("/") for x in names):
            raise NoGo("unsafe ZIP path")
        apps={x.split("/")[1] for x in names if x.startswith("Payload/") and x.count("/")>=2 and x.split("/")[1].endswith(".app")}
        if len(apps)!=1:raise NoGo("expected one IPA app")
        prefix="Payload/"+next(iter(apps))+"/"
        plist_name=prefix+"Info.plist"
        if plist_name not in names:raise NoGo("missing Info.plist")
        zinfo=z.getinfo(plist_name)
        if zinfo.file_size>1000000:raise NoGo("oversized Info.plist")
        info=plistlib.loads(z.read(plist_name))
        bundle=info.get("CFBundleIdentifier")
        if not isinstance(bundle,str) or not bundle:raise NoGo("invalid bundle identifier")
        if expected_id and bundle!=expected_id:raise NoGo("bundle ID mismatch")
        base=prefix+"default_mount/usr/local/"
        required=[base+"lib/minis-dev-ultra/native_crash.py",
                  base+"lib/minis-dev-ultra/native_diagnostics_LICENSE.txt"]
        missing=[x for x in required if x not in names]
        old_bridge=[x for x in names if x.endswith("bin/minis-apelin") or x.endswith("lib/minis-dev-ultra/apelin_bridge.py")]
        sign=prefix+"_CodeSignature/CodeResources"
        present=sign in names
        if missing or old_bridge:raise NoGo("bundled native diagnostics missing or old bridge remains")
        if not present:raise NoGo("signature resource metadata missing")
        return {"ipa_sha256":digest,"bundle_id":bundle,
                "native_crash_included":True,
                "apelin_bridge_absent":True,
                "codesign_resources_present":present,
                "cryptographic_signature_validated":False,
                "ad_hoc_installation_validated":False,
                "app_installation_tested":False,
                "warning":"CodeResources presence is NOT codesign verification; test install separately"}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="cmd",required=True)
    doc=sub.add_parser("doctor",help="read-only toolchain and SDK inventory")
    doc.add_argument("--sdk-root",action="append",default=[])
    t=sub.add_parser("triage",help="crash/jetsam/hang/resource/panic offline IPS")
    t.add_argument("ips");t.add_argument("--binary",action="append",default=[])
    m=sub.add_parser("macho",help="delegate to verified Minis ReverseLab")
    m.add_argument("file")
    i=sub.add_parser("ipa-gate",help="static IPA identity and bridge absence check")
    i.add_argument("ipa");i.add_argument("--expected-id")
    for q in (doc,t,m,i):q.add_argument("--out",help="new output JSON file (never overwrite)")
    args=p.parse_args(argv)
    try:
        if args.cmd=="doctor": result=doctor(args.sdk_root)
        elif args.cmd=="triage":result=triage(args.ips,args.binary)
        elif args.cmd=="macho":result=macho(args.file)
        else:result=ipa_gate(args.ipa,args.expected_id)
        json_output(result,args.out)
    except (NoGo,OSError,ValueError,ImportError,zipfile.BadZipFile) as e:
        print("NO-GO: "+str(e),file=sys.stderr)
        return 2
    return 0
if __name__=="__main__":sys.exit(main())
