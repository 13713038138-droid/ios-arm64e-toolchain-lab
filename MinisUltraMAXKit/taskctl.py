#!/usr/bin/env python3
"""Offline durable task journal for Minis Dev Ultra. It records checkpoints; it does not execute commands."""
import argparse,datetime as dt,json,os,pathlib,re,secrets,sys,tempfile
ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
REDACT=[re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),re.compile(r"\bAKIA[A-Z0-9]{16}\b"),re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")]
TRANS={"planned":{"running","blocked","cancelled"},"running":{"blocked","passed","failed","cancelled"},"blocked":{"running","failed","cancelled"},"failed":{"running"},"passed":set(),"cancelled":set()}
def now():return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def root():
 p=os.environ.get("MINIS_DEV_ULTRA_STATE")
 return (pathlib.Path(p).expanduser() if p else pathlib.Path.home()/".local/state/minis-dev-ultra").resolve()/"tasks"
def clean(s):
 s=str(s)
 for r in REDACT:s=r.sub("[REDACTED]",s)
 return s[:1200]
def directory(i):
 if not ID.fullmatch(i):raise ValueError("NO-GO: invalid task id")
 d=root()/i
 if d.exists() and d.is_symlink():raise ValueError("NO-GO: symlink task path refused")
 return d
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd,tmp=tempfile.mkstemp(prefix=".tmp-",dir=str(p.parent))
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump(x,f,ensure_ascii=False,indent=2,sort_keys=True);f.write("\n");f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 except Exception:
  try:os.unlink(tmp)
  except OSError:pass
  raise
def emit(x):print(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True))
def load(i):
 d=directory(i);p=d/"task.json"
 if not p.is_file():raise FileNotFoundError("NO-GO: task not found: "+i)
 x=json.loads(p.read_text())
 if x.get("id")!=i or x.get("schema")!=1:raise ValueError("NO-GO: metadata mismatch")
 return d,x
def event(d,kind,msg,details=None):
 row={"time":now(),"kind":kind,"message":clean(msg)}
 if details:row["details"]=details
 fd=os.open(str(d/"events.jsonl"),os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
 try:os.write(fd,(json.dumps(row,sort_keys=True)+"\n").encode());os.fsync(fd)
 finally:os.close(fd)
def create(a):
 i=a.id or "task-"+dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+secrets.token_hex(3)
 d=directory(i);d.parent.mkdir(parents=True,exist_ok=True,mode=0o700);d.mkdir(mode=0o700)
 x={"schema":1,"id":i,"title":clean(a.title)[:200],"project":str(pathlib.Path(a.project).expanduser().resolve()),"status":"planned","checkpoint":None,"created_at":now(),"updated_at":now()}
 write(d/"task.json",x);event(d,"created","Task created");emit({"status":"CREATED","task":x});return 0
def listing(a):
 rows=[]
 if root().is_dir():
  for d in root().iterdir():
   if d.is_symlink() or not d.is_dir() or not ID.fullmatch(d.name):continue
   try:_,x=load(d.name);rows.append({k:x.get(k) for k in ("id","title","project","status","updated_at")})
   except (OSError,ValueError,json.JSONDecodeError):pass
 emit({"count":len(rows),"tasks":sorted(rows,key=lambda x:x.get("updated_at") or "",reverse=True)});return 0
def show(a):
 d,x=load(a.id);events=[]
 if (d/"events.jsonl").exists():
  for line in (d/"events.jsonl").read_text(errors="replace").splitlines()[-max(1,min(a.limit,200)):]:
   try:events.append(json.loads(line))
   except json.JSONDecodeError:events.append({"kind":"corrupt","message":"invalid event omitted"})
 emit({"task":x,"events":events});return 0
def checkpoint(a):
 d,x=load(a.id)
 if x["status"] not in ("planned","running","blocked"):raise ValueError("NO-GO: terminal task cannot be checkpointed")
 c={"stage":clean(a.stage)[:100],"next_step":clean(a.next_step)[:300],"evidence":clean(a.evidence)[:800],"time":now()}
 if not c["stage"] or not c["next_step"]:raise ValueError("NO-GO: stage and next-step required")
 x["checkpoint"]=c;x["updated_at"]=now();write(d/"task.json",x);event(d,"checkpoint",c["stage"]+": "+c["next_step"],{"evidence":c["evidence"]});emit({"status":"CHECKPOINTED","checkpoint":c});return 0
def status(a):
 d,x=load(a.id);old,new=x["status"],a.value
 if new not in TRANS.get(old,set()):raise ValueError("NO-GO: disallowed status transition "+old+" -> "+new)
 if old=="failed" and new=="running" and not x.get("checkpoint"):raise ValueError("NO-GO: failed task needs checkpoint before resume")
 x["status"]=new;x["updated_at"]=now();write(d/"task.json",x);event(d,"status",old+" -> "+new);emit({"status":"UPDATED","from":old,"to":new});return 0
def resume(a):
 d,x=load(a.id)
 if x["status"] not in ("blocked","failed") or not x.get("checkpoint"):raise ValueError("NO-GO: resume needs blocked/failed task and checkpoint")
 old=x["status"];x["status"]="running";x["updated_at"]=now();write(d/"task.json",x);event(d,"status","resumed from "+old,{"checkpoint":x["checkpoint"]});emit({"status":"RESUMED","next_step":x["checkpoint"]["next_step"],"checkpoint":x["checkpoint"]});return 0
def note(a):
 d,x=load(a.id);event(d,a.kind,clean(a.message));x["updated_at"]=now();write(d/"task.json",x);emit({"status":"RECORDED","id":a.id});return 0
def main(argv=None):
 p=argparse.ArgumentParser(description="Durable task journal only; no shell execution/process-survival claims");s=p.add_subparsers(dest="cmd",required=True)
 q=s.add_parser("create");q.add_argument("--title",required=True);q.add_argument("--project",required=True);q.add_argument("--id");q.set_defaults(fn=create)
 q=s.add_parser("list");q.set_defaults(fn=listing)
 q=s.add_parser("show");q.add_argument("id");q.add_argument("--limit",type=int,default=50);q.set_defaults(fn=show)
 q=s.add_parser("checkpoint");q.add_argument("id");q.add_argument("--stage",required=True);q.add_argument("--next-step",required=True);q.add_argument("--evidence",default="");q.set_defaults(fn=checkpoint)
 q=s.add_parser("status");q.add_argument("id");q.add_argument("--value",choices=tuple(TRANS),required=True);q.set_defaults(fn=status)
 q=s.add_parser("resume");q.add_argument("id");q.set_defaults(fn=resume)
 q=s.add_parser("event");q.add_argument("id");q.add_argument("--kind",choices=("note","command","test","blocker","approval"),default="note");q.add_argument("--message",required=True);q.set_defaults(fn=note)
 a=p.parse_args(argv)
 try:return a.fn(a)
 except (OSError,ValueError,json.JSONDecodeError) as e:print("NO-GO:",e,file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
