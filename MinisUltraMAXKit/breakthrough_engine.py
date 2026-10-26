#!/usr/bin/env python3
"""R61 evidence-driven read-only investigation for Minis engineer agent.

Never executes probe-supplied commands, calls a model, changes project files,
installs, networks, or asserts device acceptance. An explicitly approved model
bridge may request bounded and redacted source evidence.
"""
import hashlib
import os
from pathlib import Path
import re
import autopilot

MAX_OUTPUT=3000
MAX_BYTES=256*1024
MAX_FILES=180
MAX_SEARCH_BYTES=4*1024*1024
ALLOWED={".py",".swift",".m",".mm",".h",".hpp",".c",".cc",".cpp",".xm",".x",".rs",".go",".kt",".java",".js",".ts"}
DENIED={".git",".env","secrets","credentials","private_keys","node_modules",".venv","build","dist","DerivedData"}
SECRET=re.compile(r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret|password|private[_-]?key|authorization|bearer\s|\bsecret\b|credential)")
TRACEBACK=re.compile(r'File "([^"\n]+)", line (\d+)')
ERROR=re.compile(r"(?:^|\n)\s*(?:E\s+|error:|fatal error:|.*?(?:Error|Exception|AssertionError):)",re.I)

def scrub(v):
    text="\n".join("[REDACTED SENSITIVE LINE]" if SECRET.search(line) else line[:250]
                    for line in str(v).splitlines())
    return autopilot.clean(text)[:MAX_OUTPUT]

def failure_signature(excerpt):
    s=str(excerpt or "")
    s=re.sub(r"0x[0-9a-fA-F]{6,}","0xHEX",s)
    s=re.sub(r"line\s+\d+","line N",s)
    s=re.sub(r"/tmp/[\w./-]+","/tmp/TEMP",s)
    s=re.sub(r"\s+"," ",s).strip()[-1200:]
    return hashlib.sha256(s.encode()).hexdigest()[:20]

def diagnose(result):
    failed=[x for x in result.get("checks",[]) if isinstance(x,dict) and x.get("outcome")!="pass"]
    if not failed and isinstance(result.get("cached_failed_check"),dict):
        failed=[result["cached_failed_check"]]
    if not failed:
        return {"classification":"no_failed_check","evidence":"","failure_signature":None,"has_actual_failure":False}
    entry=failed[-1]; data=str(entry.get("excerpt") or "")
    lower=data.lower()
    if entry.get("outcome")=="timeout":category="timeout"
    elif any(x in lower for x in ("modulenotfounderror","no module named","module not found","cannot find module")):category="missing_dependency"
    elif any(x in lower for x in ("undefined symbols","undefined reference","ld: symbol","linker command failed")):category="linker_abi"
    elif any(x in lower for x in ("permission denied","operation not permitted","sandbox")):category="permission"
    elif any(x in lower for x in ("assertionerror","assertion failed","failed (failures","failed (errors")):category="behavior_regression"
    elif any(x in lower for x in ("syntaxerror","compile error","error:","fatal error:")):category="compilation"
    elif entry.get("outcome")=="not_verified":category="test_discovery"
    else:category="unknown"
    causal=next((x for x in data[-3000:].splitlines() if ERROR.search(x)),None)
    if causal is None:causal=next((x for x in reversed(data.splitlines()) if x.strip()),"")
    frames=TRACEBACK.findall(data)
    return {"classification":category,
            "test_step":str(entry.get("step",""))[:80],"outcome":entry.get("outcome"),
            "failure_signature":failure_signature(data),
            "causal_error":scrub(causal)[:480],
            "location":{"path":frames[-1][0],"line":int(frames[-1][1])} if frames else None,
            "evidence":scrub(data[-3000:])[-1600:],
            "has_actual_failure":True}

def safe_source(project,relative):
    root=Path(project).resolve(strict=True)
    if not isinstance(relative,str) or not relative or len(relative)>350:
        raise ValueError("NO-GO invalid probe path")
    p=Path(relative)
    if p.is_absolute() or ".." in p.parts or any(x in DENIED for x in p.parts):
        raise ValueError("NO-GO path outside safe source scope")
    if p.suffix not in ALLOWED:raise ValueError("NO-GO source-code-only probe")
    target=root
    for part in p.parts:
        target=target/part
        if target.is_symlink():raise ValueError("NO-GO symlink")
    target=target.resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size>MAX_BYTES:
        raise ValueError("NO-GO source unavailable or oversized")
    return target

def probe(project,request):
    if not isinstance(request,dict):raise ValueError("NO-GO probe request must be an object")
    kind=request.get("kind")
    if kind=="source_context":
        source=safe_source(project,request.get("path"));line=request.get("line")
        if type(line) is not int or not 1<=line<=100000:raise ValueError("NO-GO invalid line")
        lines=source.read_text(encoding="utf8",errors="replace").splitlines()
        lo,hi=max(0,line-11),min(len(lines),line+10)
        excerpt="\n".join("%d: %s"%(i+1,lines[i]) for i in range(lo,hi))
        return {"kind":kind,"path":str(source.relative_to(Path(project).resolve())),
                "range":[lo+1,hi],"content":scrub(excerpt),"read_only":True}
    if kind=="find_symbol":
        needle=request.get("symbol")
        if not isinstance(needle,str) or not 3<=len(needle)<=70 or re.fullmatch(r"[\w.:-]+",needle) is None:
            raise ValueError("NO-GO invalid symbol")
        root=Path(project).resolve(strict=True)
        hits=[];count=0;total=0;limited=False
        for directory,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(x for x in dirs if x not in DENIED and not (Path(directory)/x).is_symlink())
            for name in sorted(files):
                file=Path(directory)/name
                if file.suffix not in ALLOWED or file.is_symlink() or not file.is_file():continue
                size=file.stat().st_size
                if size>MAX_BYTES:continue
                if count>=MAX_FILES or total+size>MAX_SEARCH_BYTES:
                    limited=True;break
                count+=1;total+=size
                for i,line in enumerate(file.read_text(encoding="utf8",errors="replace").splitlines(),1):
                    if needle in line and not SECRET.search(line):
                        hits.append({"path":str(file.relative_to(root)),"line":i,"text":scrub(line)[:150]})
                        if len(hits)>=12:break
                if len(hits)>=12:break
            if limited or len(hits)>=12:break
        return {"kind":kind,"matches":hits,"files_scanned":count,"limited":limited,"read_only":True}
    raise ValueError("NO-GO unsupported probe (no shell/network)")

def strategic_hint(previous,current):
    if not previous:
        return {"change":"first_failure","require":"form falsifiable root-cause hypothesis"}
    old=previous.get("failure_signature");new=current.get("failure_signature")
    if old and new and old==new:
        return {"change":"same_failure","require":"change hypothesis or gather different evidence; avoid same patch"}
    return {"change":"failure_changed","require":"check whether new error is downstream of previous fix"}
