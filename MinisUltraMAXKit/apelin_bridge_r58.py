#!/usr/bin/env python3
"""Minis R5.8 to Apelin Console read-only bridge. No direct daemon RPC."""
import argparse, hashlib, json, pathlib, re, secrets, shlex, subprocess, sys
OPS=("hello","extensionList","sdkList","toolchainStatus")
def payload():
    return (json.dumps({"name":"Minis Apelin read-only query","steps":[{"op":x,"label":x} for x in OPS]})+"\n").encode()
def check(token):
    if not re.fullmatch("[a-f0-9]{16}",token): raise ValueError("unsafe run token")
    return token
def stage_script(t):
    t=check(t)
    return """set -eu
umask 077
d="$HOME/Documents/wiki.qaq.apelin/console/inbox"
mkdir -p "$d"
if [ -e "$d/minis-r58-%s.json" ]; then exit 8; fi
cat > "$d/.minis-r58-%s.json"
test -s "$d/.minis-r58-%s.json"
mv "$d/.minis-r58-%s.json" "$d/minis-r58-%s.json"
echo STAGED
"""%(t,t,t,t,t)
def collect_script(t):
    t=check(t)
    return """set -eu
d="$HOME/Documents/wiki.qaq.apelin/console"
for marker in "$d"/done/*-minis-r58-%s.json "$d"/running/*-minis-r58-%s.json; do
  if [ -f "$marker" ]; then
    name="$(basename "$marker")"
    runid="$(printf '%%s' "$name" | sed 's/-minis-r58-%s\\.json$//')"
    test -f "$d/out/$runid.jsonl" || exit 4
    cat "$d/out/$runid.jsonl"; exit 0
  fi
done
test -f "$d/inbox/minis-r58-%s.json" && { echo "PENDING: open Apelin" >&2; exit 3; }
echo NO_RESULT >&2
exit 5
"""%(t,t,t,t)
def ssh(a,script,data=None):
    for val in (a.host,a.user):
        if not re.fullmatch("[A-Za-z0-9][A-Za-z0-9._:-]{0,254}",val):
            raise ValueError("unsafe SSH destination")
    if not (1<=a.port<=65535): raise ValueError("invalid port")
    cmd=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=10","-p",str(a.port)]
    if a.identity: cmd+=["-i",a.identity]
    cmd+=[a.user+"@"+a.host,"sh -c "+shlex.quote(script)]
    return subprocess.run(cmd,input=data,capture_output=True,timeout=45)
def summarize(p):
    raw=pathlib.Path(p).read_bytes()
    rows=[json.loads(x) for x in raw.splitlines() if x.strip()]
    if any(not isinstance(x,dict) for x in rows): raise ValueError("invalid JSONL")
    seen=[x for x in rows if x.get("type")=="step.result"]
    end=next((x for x in reversed(rows) if x.get("type")=="run.end"),None)
    good=bool(end and end.get("ok") is True and len(seen)==len(OPS) and
              [x.get("op") for x in seen]==list(OPS) and all(x.get("ok") is True for x in seen))
    return {"source":"Apelin Console JSONL","sha256":hashlib.sha256(raw).hexdigest(),
            "passed":good,"finished":bool(end),"steps":[{"op":x.get("op"),"ok":x.get("ok")} for x in seen],
            "runtime_verified":False,"abi_verified":False,"note":"Only read-only inventory; no build/install"}
def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    g=sub.add_parser("generate");g.add_argument("--out",required=True)
    st=sub.add_parser("stage");co=sub.add_parser("collect")
    for x in (st,co):
        x.add_argument("--host",required=True);x.add_argument("--user",default="mobile")
        x.add_argument("--port",type=int,default=22);x.add_argument("--identity")
    co.add_argument("--token",required=True);co.add_argument("--out",required=True)
    su=sub.add_parser("summarize");su.add_argument("--infile",required=True)
    a=p.parse_args()
    try:
        if a.cmd=="generate":
            with open(a.out,"xb") as f:f.write(payload())
            result={"file":a.out}
        elif a.cmd=="stage":
            token=secrets.token_hex(8);r=ssh(a,stage_script(token),payload())
            if r.returncode:raise RuntimeError("stage rc="+str(r.returncode)+" "+r.stderr.decode(errors="replace")[:150])
            result={"token":token,"status":"STAGED","next":"Open Apelin, then collect with same host/token"}
        elif a.cmd=="collect":
            r=ssh(a,collect_script(a.token))
            if r.returncode:raise RuntimeError("collect rc="+str(r.returncode)+" "+r.stderr.decode(errors="replace")[:150])
            with open(a.out,"xb") as f:f.write(r.stdout)
            result=summarize(a.out)
        else:result=summarize(a.infile)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,RuntimeError,OSError,subprocess.TimeoutExpired,json.JSONDecodeError) as e:
        print("NO-GO: "+str(e),file=sys.stderr);return 2
    return 0
if __name__=="__main__":raise SystemExit(main())
