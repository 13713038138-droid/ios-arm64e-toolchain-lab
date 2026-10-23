#!/usr/bin/env python3
"""Offline token analysis. This never bypasses provider limits or silently edits live chat."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]')
CRITICAL = re.compile(r'(?i)(error:|fatal|fail(?:ed|ure)?|traceback|exception|crash|SIGSEGV|SIGABRT|assert|NO-GO|rollback|restore|CAS|swift_retain|security|regression|test|SHA256|evidence|warning)')
SECRET = re.compile(r'(?i)(gh[pousr]_[A-Za-z0-9_]{15,}|github_pat_|(?:api[_-]?key|secret|token|password)\s*[:=]\s*\S+)')
def estimate(s):
    cjk = CJK.findall(s)
    rest = len(s.encode()) - len(''.join(cjk).encode())
    return int(len(cjk)*1.3 + rest/4 + .999) if s else 0
def stats(s):
    counts = Counter()
    repeat = 0
    for ln in s.splitlines():
        if len(ln.strip()) < 32: continue
        h = hashlib.sha256(ln.strip().encode()).hexdigest()
        if counts[h]: repeat += estimate(ln)
        counts[h] += 1
    return dict(estimated_tokens=estimate(s), characters=len(s), lines=len(s.splitlines()),
                estimated_duplicate_line_tokens=repeat, note='heuristic only, NOT provider token count')
def pack(s, budget):
    if budget < 400: raise ValueError('budget < 400')
    lines = s.splitlines()
    critical = {i for i, x in enumerate(lines) if CRITICAL.search(x)}
    keep = set(range(min(12,len(lines)))) | set(range(max(len(lines)-12,0),len(lines)))
    for i in critical: keep.update((max(i-1,0),i))
    out = ['# Condensed COPY; original must be kept',
           'original_sha256: '+hashlib.sha256(s.encode()).hexdigest(),
           'original_lines: '+str(len(lines))]
    prev = -1
    for i in sorted(keep):
        if i > prev+1: out.append('[omitted lines %s-%s; consult original]' % (prev+2,i))
        content = lines[i]
        if SECRET.search(content): content = '[REDACTED potential credential; consult original locally]'
        out.append('L%d: %s' % (i+1,content))
        prev=i
    result = '\n'.join(out)+'\n'
    report = dict(estimated_original_tokens=estimate(s),estimated_packed_tokens=estimate(result),
                  source_sha256=hashlib.sha256(s.encode()).hexdigest(),critical_lines=len(critical),
                  kept_lines=len(keep),budget=budget,refused=estimate(result)>budget)
    return result,report
def chat(path):
    roles = Counter()
    repeats=0
    seen=set()
    invalid=[]
    for index,raw in enumerate(Path(path).read_text(encoding='utf-8',errors='replace').splitlines(),1):
        if not raw.strip(): continue
        try:
            obj=json.loads(raw)
            if not isinstance(obj,dict): raise ValueError('not message')
        except (ValueError,TypeError):
            invalid.append(index);continue
        role=str(obj.get('role',obj.get('type','unknown')))
        value=obj.get('content',obj.get('text',''))
        if isinstance(value,list):
            value='\n'.join(x.get('text','') for x in value if isinstance(x,dict) and isinstance(x.get('text'),str))
        if not isinstance(value,str): value=''
        amount=estimate(value);roles[role]+=amount
        key=hashlib.sha256((role+'\0'+value).encode()).hexdigest()
        if key in seen and len(value)>80: repeats+=amount
        seen.add(key)
    return dict(estimated_by_role=dict(roles),estimated_total_tokens=sum(roles.values()),
                estimated_repeated_turn_tokens=repeats,invalid_jsonl_lines=invalid[:50],
                note='heuristic, NOT billed tokens; never silently discard tool result or source')
def cost(inp,out,cached,price_in,price_out,price_cache):
    if min(inp,out,cached)<0 or cached>inp: raise ValueError('invalid token counts')
    rates=[Decimal(x) for x in (price_in,price_out,price_cache)]
    if any(x<0 for x in rates): raise ValueError('negative rate')
    # cached tokens are INCLUDED in input, so never charged twice
    amount=(Decimal(inp-cached)*rates[0]+Decimal(out)*rates[1]+Decimal(cached)*rates[2])/Decimal(1000000)
    return str(amount.quantize(Decimal('0.000001')))
def main(argv=None):
    p=argparse.ArgumentParser(description='Minis token diagnostics; no quota, rate or model unlock')
    sp=p.add_subparsers(dest='cmd',required=True)
    for sub in ('audit','chat','pack-log'):
        q=sp.add_parser(sub);q.add_argument('file')
        if sub=='pack-log':
            q.add_argument('--out',required=True);q.add_argument('--budget',type=int,default=6000)
    q=sp.add_parser('cost')
    for arg in ('input','output','cached'): q.add_argument('--'+arg,type=int,required=True)
    for arg in ('input-rate','output-rate','cached-rate'): q.add_argument('--'+arg,required=True)
    a=p.parse_args(argv)
    try:
        if a.cmd=='cost':
            result={'cost_at_user_supplied_rates':cost(a.input,a.output,a.cached,a.input_rate,a.output_rate,a.cached_rate),
                    'pricing':'rates supplied by caller; no live pricing or entitlement check'}
        else:
            file=Path(a.file)
            if not file.is_file() or file.stat().st_size>32*1024*1024: raise ValueError('missing or >32 MiB input')
            if a.cmd=='chat': result=chat(file)
            else:
                content=file.read_text(encoding='utf-8',errors='replace')
                if a.cmd=='audit': result=stats(content)
                else:
                    target=Path(a.out)
                    if target.resolve()==file.resolve(): raise ValueError('would overwrite original')
                    packed,result=pack(content,a.budget)
                    result['status']='NO-GO' if result['refused'] else 'PACKED'
                    if not result['refused']:
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_text(packed,encoding='utf-8')
                        result['saved_copy']=str(target)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
        return int(result.get('status')=='NO-GO')
    except (OSError,ValueError,ArithmeticError) as exc:
        print('NO-GO:',exc,file=sys.stderr);return 2
if __name__=='__main__': sys.exit(main())
