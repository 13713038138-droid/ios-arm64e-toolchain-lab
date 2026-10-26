#!/usr/bin/env python3
"""Minis native, offline iOS IPS crash diagnostic and UUID-gated Mach-O resolver.

Faithful limited Python adaptation of OwnGoal Studio Apelin's:
ApelinCrashReport/IPSDecoder.swift, CrashBodyDecoder.swift, BinaryImages.swift
and ApelinCrashSymbols/MachOSlice.swift, Symbolicator.swift.
Copyright (c) 2026 OwnGoal Studio. MIT; see native_diagnostics_LICENSE.txt.
No Apelin app, RPC, daemon, network, install, or process injection.
"""
import argparse,bisect,hashlib,json,pathlib,re,struct,sys,uuid
MAX_IPS=32*1024*1024
MAX_BINARY=512*1024*1024
MAX_IMAGES=4096
MAX_FRAMES=2048
MAX_SYMBOLS=350000
class NotVerified(ValueError):pass
def finite_number(x,label,default=None):
    if x is None:return default
    if type(x) is int and 0<=x<=0xffffffffffffffff:return x
    if isinstance(x,str) and re.fullmatch(r'(0[xX][0-9a-fA-F]+|[0-9]+)',x):
        v=int(x,0) if x.startswith(('0x','0X')) else int(x)
        if v<=0xffffffffffffffff:return v
    raise NotVerified('invalid unsigned '+label)
def limited(path,size):
    p=pathlib.Path(path)
    if not p.is_file() or p.stat().st_size>size:raise NotVerified('file missing or too large')
    return p.read_bytes()
def norm_uuid(raw):
    try:return str(uuid.UUID(str(raw))).upper()
    except (ValueError,AttributeError,TypeError) as exc:raise NotVerified('invalid UUID') from exc
def ips(path):
    raw=limited(path,MAX_IPS)
    if not raw.strip():raise NotVerified('empty IPS')
    first,sep,rest=raw.partition(b'\n')
    header={}
    try:
        header=json.loads(first)
        if not isinstance(header,dict):raise ValueError()
    except (ValueError,UnicodeError):
        header={};rest=raw
    try:body=json.loads(rest) if rest.strip() else {}
    except (ValueError,UnicodeError) as exc:raise NotVerified('invalid IPS JSON body') from exc
    if not isinstance(body,dict) or not isinstance(body.get('usedImages'),list) or not isinstance(body.get('threads'),list):
        raise NotVerified('not a crash report with image/thread evidence')
    if len(body['usedImages'])>MAX_IMAGES or len(body['threads'])>MAX_FRAMES:
        raise NotVerified('oversized IPS arrays')
    images=[]
    for ent in body['usedImages']:
        if not isinstance(ent,dict):raise NotVerified('invalid image')
        name=ent.get('name') or pathlib.PurePosixPath(str(ent.get('path',''))).name
        images.append(dict(name=str(name)[:180],uuid=norm_uuid(ent['uuid']) if ent.get('uuid') else None,
            base=finite_number(ent.get('base'),'base',0),size=finite_number(ent.get('size'),'size',0)))
    n=body.get('faultingThread')
    if type(n) is not int or not 0<=n<len(body['threads']):
        n=next((i for i,t in enumerate(body['threads']) if isinstance(t,dict) and t.get('triggered') is True),None)
    if n is None:raise NotVerified('no evidenced faulting thread')
    thread=body['threads'][n]
    if not isinstance(thread,dict) or not isinstance(thread.get('frames'),list):
        raise NotVerified('missing faulting frames')
    if len(thread['frames'])>MAX_FRAMES:raise NotVerified('too many frames')
    frames=[]
    for ent in thread['frames']:
        if not isinstance(ent,dict):raise NotVerified('bad frame')
        idx=ent.get('imageIndex')
        if type(idx) is not int or not 0<=idx<len(images):
            frames.append(dict(verified=False,reason='invalid imageIndex'));continue
        im=images[idx]
        offset=finite_number(ent.get('imageOffset'),'imageOffset')
        if offset is None or offset>=im['size'] or im['base']>0xffffffffffffffff-offset:
            frames.append(dict(verified=False,image=im['name'],reason='offset not inside image'));continue
        frames.append(dict(verified=True,image=im['name'],uuid=im['uuid'],
            image_offset=offset,address=hex(im['base']+offset),
            report_symbol=str(ent.get('symbol',''))[:180] or None))
    exception=body.get('exception') if isinstance(body.get('exception'),dict) else {}
    return dict(process=str(body.get('procName') or header.get('app_name') or header.get('name') or '')[:180],
        bug_type=str(header.get('bug_type','')),exception=dict(type=exception.get('type'),signal=exception.get('signal')),
        faulting_thread=n,frames=frames,raw_sha256=hashlib.sha256(raw).hexdigest())
def macho_slices(data):
    magic=data[:4]
    if magic in (b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'):
        if len(data)<8:raise NotVerified('short FAT header')
        count=struct.unpack_from('>I',data,4)[0]
        if not 1<=count<=32:raise NotVerified('bad FAT count')
        width=32 if magic[-1]==0xbf else 20
        if len(data)<8+count*width:raise NotVerified('short FAT slice table')
        parts=[]
        for i in range(count):
            pos=8+i*width
            start,size=struct.unpack_from('>QQ' if width==32 else '>II',data,pos+8)
            if start>len(data) or size>len(data)-start:raise NotVerified('out of bounds FAT slice')
            if data[start:start+4]==b'\xcf\xfa\xed\xfe':parts.append((start,size))
        return parts
    if magic==b'\xcf\xfa\xed\xfe':return [(0,len(data))]
    raise NotVerified('not 64-bit little-endian Mach-O')
def macho(path):
    data=limited(path,MAX_BINARY);results=[]
    digest=hashlib.sha256(data).hexdigest()
    for start,size in macho_slices(data):
        if size<32:raise NotVerified('short Mach-O header')
        magic,cpu,subtype,kind,ncmds,cmdsize,flags,reserved=struct.unpack_from('<IiiIIIII',data,start)
        if ncmds>4096 or cmdsize>size-32:raise NotVerified('invalid Mach-O commands')
        cur=start+32;end=cur+cmdsize;found=None;text=None;table=None;starts=None
        for j in range(ncmds):
            if cur+8>end:raise NotVerified('truncated load commands')
            op,sz=struct.unpack_from('<II',data,cur)
            if sz<8 or cur+sz>end:raise NotVerified('bad load command length')
            if op==0x1b:
                if sz<24:raise NotVerified('short UUID command')
                found=str(uuid.UUID(bytes=bytes(data[cur+8:cur+24]))).upper()
            elif op==0x19:
                if sz<72:raise NotVerified('short segment')
                name=data[cur+8:cur+24].split(b'\0')[0]
                vm,vm_size,file_off,file_size=struct.unpack_from('<QQQQ',data,cur+24)
                if file_off>size or file_size>size-file_off:raise NotVerified('segment out of bounds')
                if name==b'__TEXT':text=(vm,vm_size)
            elif op==0x2:
                if sz<24:raise NotVerified('short symbols command')
                table=struct.unpack_from('<IIII',data,cur+8)
            elif op==0x26:
                if sz<16:raise NotVerified('short function starts')
                starts=struct.unpack_from('<II',data,cur+8)
            cur+=sz
        if cur!=end:raise NotVerified('trailing load command bytes')
        if not found:continue
        names={}
        if table and text:
            so,n,stro,stsize=table;vm,vm_size=text
            if n>MAX_SYMBOLS or so>size or n*16>size-so or stro>size or stsize>size-stro:
                raise NotVerified('symbol table out of bounds')
            for j in range(n):
                index,type_code,sect,desc,value=struct.unpack_from('<IBBHQ',data,start+so+16*j)
                if index>=stsize or value<vm or value-vm>=vm_size:continue
                if type_code&0xe0 or (type_code&0x0e)!=0x0e:continue
                p=start+stro+index
                stop=data.find(b'\0',p,min(start+stro+stsize,p+4096))
                if stop<=p:continue
                name=data[p:stop].decode('utf8','replace')
                if len(name)<=250:names[value-vm]=name
        if starts and text:
            so,sz=starts;_,vm_size=text
            if so>size or sz>size-so:raise NotVerified('function start out of bounds')
            p=start+so;endp=p+sz;address=0
            for _ in range(MAX_SYMBOLS):
                step=0;shift=0
                while p<endp:
                    b=data[p];p+=1
                    if shift>63:raise NotVerified('ULEB overflow')
                    step|=(b&127)<<shift
                    if not b&128:break
                    shift+=7
                else:break
                if not step:break
                address+=step
                if address>=vm_size:break
                names.setdefault(address,None)
        if text:names.setdefault(text[1],None)
        positions=sorted(names)
        results.append(dict(uuid=found,sha256=digest,text_size=text[1] if text else None,
            positions=positions,names=[names[k] for k in positions]))
    return results
def analyze(report_path,binaries):
    report=ips(report_path)
    lookup={}
    for p in binaries:
        for m in macho(p):lookup.setdefault(m['uuid'],m)
    ok=0
    for f in report['frames']:
        if not f['verified']:continue
        m=lookup.get(f['uuid'])
        if not m:
            f.update(symbol=None,symbol_status='NO_MATCHING_UUID');continue
        off=f['image_offset']
        if m['text_size'] is None or off>=m['text_size']:
            f.update(symbol=None,symbol_status='OUTSIDE_TEXT');continue
        i=bisect.bisect_right(m['positions'],off)-1
        if i<0 or m['names'][i] is None:
            f.update(symbol=None,symbol_status='UNKNOWN_OR_STRIPPED');continue
        f.update(symbol=m['names'][i],symbol_offset=off-m['positions'][i],
                 symbol_status='UUID_MATCHED_SYMBOL',matched_macho_sha256=m['sha256'])
        ok+=1
    report['symbolication']=dict(resolved_frames=ok,unresolved_frames=len(report['frames'])-ok,
         scope='Mach-O nlist + LC_FUNCTION_STARTS only; no DWARF source-line attribution',
         no_apelin_dependency=True,device_test_passed=False)
    return report
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('ips')
    p.add_argument('--binary',action='append',default=[])
    p.add_argument('--out')
    a=p.parse_args(argv)
    try:
        result=json.dumps(analyze(a.ips,a.binary),indent=2,ensure_ascii=False)+'\n'
        if a.out:
            with open(a.out,'x',encoding='utf8') as f:f.write(result)
        else:sys.stdout.write(result)
    except (OSError,ValueError,struct.error,UnicodeError) as e:
        print('NO-GO: '+str(e),file=sys.stderr);return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
