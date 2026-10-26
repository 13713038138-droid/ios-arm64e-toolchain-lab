#!/usr/bin/env python3
"""Minis native offline iOS .ips crash triage and UUID-gated Mach-O symbols.

Adapted from OwnGoal Studio Apelin's MIT-licensed IPSDecoder,
CrashBodyDecoder, MachOSlice and Symbolicator approaches.
Copyright (c) 2026 OwnGoal Studio. See native_diagnostics_LICENSE.txt.
No Apelin app/daemon, network, jailbreak mutation, hook, or binary execution.
"""
import argparse
import bisect
import hashlib
import json
import pathlib
import re
import struct
import sys
import uuid

MAX_REPORT=32*1024*1024
MAX_BINARY=512*1024*1024
MAX_SYMBOLS=350000
class NotVerified(ValueError): pass

def bounded(path,limit):
    p=pathlib.Path(path)
    if not p.is_file() or p.stat().st_size>limit: raise NotVerified("missing or oversized input")
    return p.read_bytes()

def number(value,name):
    if type(value) is int and 0<=value<2**64:return value
    if isinstance(value,str) and re.fullmatch(r"(0[xX][0-9a-fA-F]+|[0-9]+)",value):
        x=int(value,0) if value.lower().startswith("0x") else int(value)
        if 0<=x<2**64:return x
    raise NotVerified("invalid unsigned "+name)

def normalize_uuid(value):
    try:return str(uuid.UUID(str(value))).upper()
    except (ValueError,TypeError,AttributeError) as e:raise NotVerified("invalid UUID") from e

def report(path):
    data=bounded(path,MAX_REPORT)
    head,sep,tail=data.partition(b"\n")
    try:
        hdr=json.loads(head)
        if not isinstance(hdr,dict):raise NotVerified("IPS header is not an object")
        body=json.loads(tail) if tail.strip() else {}
    except (ValueError,UnicodeError) as e:raise NotVerified("invalid IPS JSON") from e
    if not isinstance(body,dict) or not isinstance(body.get("threads"),list) or not isinstance(body.get("usedImages"),list):
        raise NotVerified("not an IPS crash body")
    if len(body["usedImages"])>4096 or len(body["threads"])>2048:
        raise NotVerified("oversize IPS collections")
    imgs=[]
    for raw in body["usedImages"]:
        if not isinstance(raw,dict):raise NotVerified("bad image")
        imgs.append({"name":str(raw.get("name") or pathlib.PurePosixPath(str(raw.get("path",""))).name)[:200],
                     "uuid":normalize_uuid(raw["uuid"]) if raw.get("uuid") else None,
                     "base":number(raw.get("base",0),"base"),
                     "size":number(raw.get("size",0),"size")})
    index=body.get("faultingThread")
    if type(index) is not int or not 0<=index<len(body["threads"]):
        index=next((i for i,t in enumerate(body["threads"]) if isinstance(t,dict) and t.get("triggered") is True),None)
    if index is None:raise NotVerified("faulting thread not evidenced")
    thread=body["threads"][index]
    if not isinstance(thread,dict) or not isinstance(thread.get("frames"),list) or len(thread["frames"])>2048:
        raise NotVerified("invalid faulting thread")
    frames=[]
    for f in thread["frames"]:
        if not isinstance(f,dict):raise NotVerified("bad frame")
        n=f.get("imageIndex")
        if type(n) is not int or not 0<=n<len(imgs):
            frames.append({"verified":False,"reason":"invalid image index"});continue
        im=imgs[n]
        off=number(f.get("imageOffset"),"imageOffset")
        if off>=im["size"] or im["base"]+off>=2**64:
            frames.append({"verified":False,"reason":"image range mismatch","image":im["name"]});continue
        frames.append({"verified":True,"image":im["name"],"uuid":im["uuid"],
                       "offset":off,"address":hex(im["base"]+off),
                       "report_symbol":str(f.get("symbol",""))[:180] or None})
    exc=body.get("exception") if isinstance(body.get("exception"),dict) else {}
    return {"process":str(body.get("procName") or hdr.get("app_name") or hdr.get("name") or "")[:180],
            "bug_type":str(hdr.get("bug_type",""))[:32],
            "exception":{"type":exc.get("type"),"signal":exc.get("signal")},
            "faulting_thread":index,"frames":frames,"sha256":hashlib.sha256(data).hexdigest()}

def slices(data):
    magic=data[:4]
    if magic==b"\xcf\xfa\xed\xfe":return [(0,len(data))]
    if magic not in (b"\xca\xfe\xba\xbe",b"\xca\xfe\xba\xbf"):
        raise NotVerified("not a 64-bit little endian Mach-O")
    if len(data)<8:raise NotVerified("truncated FAT header")
    n=struct.unpack_from(">I",data,4)[0]
    if not 0<n<=32:raise NotVerified("invalid FAT count")
    width=32 if magic==b"\xca\xfe\xba\xbf" else 20
    if len(data)<8+width*n:raise NotVerified("short FAT table")
    out=[]
    for i in range(n):
        p=8+width*i
        start,size=struct.unpack_from(">QQ" if width==32 else ">II",data,p+8)
        if start>len(data) or size>len(data)-start:raise NotVerified("FAT slice out of bounds")
        if data[start:start+4]==b"\xcf\xfa\xed\xfe":out.append((start,size))
    return out

def inspect_binary(path):
    data=bounded(path,MAX_BINARY)
    found=[]
    for start,size in slices(data):
        end=start+size
        if size<32:raise NotVerified("short Mach-O")
        hdr=struct.unpack_from("<IiiIIIII",data,start)
        _,cpu,subtype,_,ncmds,cmdbytes,_,_=hdr
        if ncmds>4096 or cmdbytes>size-32:raise NotVerified("bad load commands")
        pos=start+32;limit=pos+cmdbytes
        uid=None;text_vm=None;text_size=None;syms=None;funcs=None
        for _ in range(ncmds):
            if pos+8>limit:raise NotVerified("truncated load command")
            cmd,amount=struct.unpack_from("<II",data,pos)
            if amount<8 or amount%8!=0 or pos+amount>limit:raise NotVerified("invalid command size")
            if cmd==0x1b:
                if amount<24:raise NotVerified("short LC_UUID")
                uid=str(uuid.UUID(bytes=bytes(data[pos+8:pos+24]))).upper()
            elif cmd==0x19:
                if amount<72:raise NotVerified("short LC_SEGMENT_64")
                name=data[pos+8:pos+24].split(b"\0",1)[0]
                vm,vs,fo,fs=struct.unpack_from("<QQQQ",data,pos+24)
                if fo>size or fs>size-fo:raise NotVerified("invalid segment")
                if name==b"__TEXT":text_vm,text_size=vm,vs
            elif cmd==0x2:
                if amount<24:raise NotVerified("short LC_SYMTAB")
                syms=struct.unpack_from("<IIII",data,pos+8)
            elif cmd==0x26:
                if amount<16:raise NotVerified("short LC_FUNCTION_STARTS")
                funcs=struct.unpack_from("<II",data,pos+8)
            pos+=amount
        if pos!=limit:raise NotVerified("load commands do not fill header")
        if not uid:continue
        entries={}
        if syms and text_vm is not None:
            symoff,nsym,stroff,strsize=syms
            if nsym>MAX_SYMBOLS or symoff>size or nsym*16>size-symoff or stroff>size or strsize>size-stroff:
                raise NotVerified("bad symbols")
            for i in range(nsym):
                strx,ntype,_,_,value=struct.unpack_from("<IBBHQ",data,start+symoff+i*16)
                if strx>=strsize or value<text_vm or (text_size and value>=text_vm+text_size):continue
                if ntype&0x0e!=0x0e or ntype&0xe0:continue
                offset=start+stroff+strx
                stop=data.find(b"\0",offset,min(start+stroff+strsize,offset+2048))
                if stop<=offset:continue
                entries[value-text_vm]=data[offset:stop].decode("utf-8","replace")[:250]
        if funcs and text_size is not None:
            fo,fs=funcs
            if fo>size or fs>size-fo:raise NotVerified("invalid function starts")
            p=start+fo;end_func=p+fs;addr=0
            for _ in range(MAX_SYMBOLS):
                v=0;shift=0
                while p<end_func:
                    b=data[p];p+=1
                    if shift>=64:raise NotVerified("function start ULEB overflow")
                    v|=(b&127)<<shift
                    if not b&128:break
                    shift+=7
                else:break
                if v==0:break
                addr+=v
                if addr>=text_size:break
                entries.setdefault(addr,None)
        if text_size is not None:entries.setdefault(text_size,None)
        starts=sorted(entries)
        found.append({"uuid":uid,"arch":"arm64e" if cpu==0x100000c and subtype&255==2 else "arm64" if cpu==0x100000c else "other",
                      "text_size":text_size,"starts":starts,"names":[entries[x] for x in starts],
                      "sha256":hashlib.sha256(data).hexdigest()})
    return found

def analyze(ips,binaries):
    item=report(ips)
    db={}
    for path in binaries:
        for binary in inspect_binary(path):db.setdefault(binary["uuid"],binary)
    good=0;bad=0
    for frame in item["frames"]:
        if not frame["verified"]:bad+=1;continue
        candidate=db.get(frame["uuid"]) if frame.get("uuid") else None
        if candidate is None:
            frame["symbol_status"]="NO_MATCHING_UUID";bad+=1;continue
        off=frame["offset"];limit=candidate["text_size"]
        if limit is None or off>=limit:
            frame["symbol_status"]="OUTSIDE_TEXT";bad+=1;continue
        pos=bisect.bisect_right(candidate["starts"],off)-1
        if pos<0 or candidate["names"][pos] is None:
            frame["symbol_status"]="UNKNOWN_OR_STRIPPED";bad+=1;continue
        frame["symbol"]=candidate["names"][pos]
        frame["displacement"]=off-candidate["starts"][pos]
        frame["symbol_status"]="UUID_MATCHED_SYMBOL"
        frame["binary_sha256"]=candidate["sha256"];good+=1
    item["symbolication"]={"matched_frames":good,"unresolved_frames":bad,
                           "scope":"static Mach-O symbols and LC_FUNCTION_STARTS; no DWARF lines",
                           "requires_apelin":False,"device_verified":False}
    return item

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("ips");a.add_argument("--binary",action="append",default=[])
    a.add_argument("--out")
    args=a.parse_args()
    try:
        value=json.dumps(analyze(args.ips,args.binary),ensure_ascii=False,indent=2)+"\n"
        if args.out:
            with open(args.out,"x",encoding="utf-8") as f:f.write(value)
        else:sys.stdout.write(value)
    except (NotVerified,ValueError,OSError,struct.error,UnicodeError) as exc:
        print("NO-GO: "+str(exc),file=sys.stderr);return 2
    return 0
if __name__=="__main__":sys.exit(main())
