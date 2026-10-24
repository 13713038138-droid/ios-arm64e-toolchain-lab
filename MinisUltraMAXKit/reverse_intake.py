#!/usr/bin/env python3
"""ReverseLab: read-only IPA / DEB archive to Mach-O analyzer.

Never run package scripts, install bundles, or extract files onto the disk.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import zipfile

import reverse_lab as core

LIMIT_ITEM=256*1024*1024
LIMIT_ARCHIVE=1024*1024*1024
MAX_MEMBERS=15000
MAX_SHOW=200
MAGIC=(*core.MAGICS, *core.FAT_MAGICS)

class IntakeError(ValueError):
    pass

def safe_name(name):
    name=name.replace("\\", "/")
    return bool(name) and not name.startswith("/") and ".." not in name.split("/") and "\x00" not in name

def ar_data(path):
    with path.open("rb") as stream:
        if stream.read(8)!=b"!<arch>\n":
            raise IntakeError("invalid Debian ar header")
        while True:
            header=stream.read(60)
            if not header: break
            if len(header)!=60 or header[58:60]!=bytes([0x60,0x0a]):
                raise IntakeError("truncated Debian ar member header")
            name=header[:16].decode("ascii","replace").strip().rstrip("/")
            try: size=int(header[48:58].decode("ascii").strip())
            except ValueError as exc: raise IntakeError("invalid ar member size") from exc
            if size<0 or size>LIMIT_ARCHIVE: raise IntakeError("oversized Debian ar member")
            if name.startswith("data.tar."):
                if not name.endswith((".xz",".gz",".bz2")):
                    raise IntakeError("unsupported DEB data.tar compression: "+name)
                blob=stream.read(size)
                if len(blob)!=size: raise IntakeError("truncated Debian data archive")
                return blob
            stream.seek(size+(size%2),1)
    raise IntakeError("no supported data.tar.xz/gz/bz2 member in DEB")

def package_entries(path,kind):
    if kind=="ipa":
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)>MAX_MEMBERS: raise IntakeError("excess IPA member count")
            for entry in entries:
                if not safe_name(entry.filename): raise IntakeError("unsafe IPA member path")
                if not entry.is_dir() and entry.file_size<=LIMIT_ITEM:
                    yield entry.filename,entry.file_size
    else:
        with tarfile.open(fileobj=io.BytesIO(ar_data(path)),mode="r:*") as archive:
            for index,entry in enumerate(archive):
                if index>=MAX_MEMBERS: raise IntakeError("excess DEB member count")
                if not safe_name(entry.name): raise IntakeError("unsafe DEB member path")
                if entry.isfile() and entry.size<=LIMIT_ITEM:
                    yield entry.name,entry.size

def candidate(name):
    leaf=name.replace("\\","/").rsplit("/",1)[-1]
    if name.endswith((".dylib",".so")): return True
    if ".framework/" in name and leaf==name.split(".framework/",1)[1].split("/",1)[0]:
        return True
    if ".app/" in name and leaf and "." not in leaf: return True
    if any(x in name for x in ("DynamicLibraries/","/usr/bin/","/usr/lib/")):
        return "." not in leaf or leaf.endswith((".dylib",".so"))
    return False

def read_entry(path,kind,wanted):
    if not safe_name(wanted): raise IntakeError("invalid member name")
    if kind=="ipa":
        with zipfile.ZipFile(path) as archive:
            try: entry=archive.getinfo(wanted)
            except KeyError as exc: raise IntakeError("IPA member not found") from exc
            if entry.is_dir() or entry.file_size>LIMIT_ITEM:
                raise IntakeError("IPA member is not a bounded file")
            if entry.compress_size==0 and entry.file_size:
                raise IntakeError("invalid compressed member size")
            if entry.compress_size and entry.file_size/entry.compress_size>500:
                raise IntakeError("suspicious IPA compression ratio")
            with archive.open(entry) as stream: blob=stream.read(LIMIT_ITEM+1)
    else:
        with tarfile.open(fileobj=io.BytesIO(ar_data(path)),mode="r:*") as archive:
            try: entry=archive.getmember(wanted)
            except KeyError as exc: raise IntakeError("DEB member not found") from exc
            if not entry.isfile() or entry.size>LIMIT_ITEM:
                raise IntakeError("DEB member is not a bounded regular file")
            with archive.extractfile(entry) as stream: blob=stream.read(LIMIT_ITEM+1)
    if len(blob)>LIMIT_ITEM: raise IntakeError("member exceeds uncompressed size bound")
    return blob

def identify(path):
    path=Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise IntakeError("input must be a regular file, not a symlink")
    size=path.stat().st_size
    if size<8 or size>LIMIT_ARCHIVE: raise IntakeError("unsupported input size")
    with path.open("rb") as stream: magic=stream.read(8)
    if magic[:4] in MAGIC: return path,"macho"
    if magic[:4]==b"PK\x03\x04" and zipfile.is_zipfile(path): return path,"ipa"
    if magic==b"!<arch>\n": return path,"deb"
    raise IntakeError("unsupported file: expected Mach-O / IPA / DEB")

def analyze_binary(blob,search,at,count):
    if blob[:4] not in MAGIC: raise IntakeError("selected member is not 64-bit Mach-O")
    if blob[:4] not in core.FAT_MAGICS:
        return [core.analyze_slice(blob,0,len(blob),search,at,count)]
    order,is64=core.FAT_MAGICS[blob[:4]]
    n=struct.unpack_from(order+"I",blob,4)[0]
    if n<1 or n>core.MAX_SLICES: raise IntakeError("invalid universal binary slice count")
    size=32 if is64 else 20
    table_end=8+n*size
    core.region(8,table_end-8,0,len(blob))
    spans=[]
    result=[]
    for j in range(n):
        entry=struct.unpack_from(order+("iiQQII" if is64 else "iiIII"),blob,8+j*size)
        off,length=entry[2:4]
        if off<table_end: raise IntakeError("slice overlaps fat header")
        core.region(off,length,0,len(blob))
        if any(off<b and a<off+length for a,b in spans):
            raise IntakeError("fat slices overlap")
        spans.append((off,off+length))
        result.append(core.analyze_slice(blob,off,length,search,at,count))
    return result

def inspect(path,member=None,search="",at=None,count=24):
    path,kind=identify(path)
    if kind=="macho":
        if member: raise IntakeError("--member is not valid for Mach-O files")
        return core.analyze(path,search,at,count)
    entries=list(package_entries(path,kind))
    names=[n for n,_ in entries if candidate(n)]
    result={"tool":"Minis ReverseLab archive intake","archive":str(path),
        "archive_kind":kind,"archive_members":len(entries),
        "candidates":names[:MAX_SHOW],"candidate_count":len(names),
        "candidate_list_truncated":len(names)>MAX_SHOW,"status":"selection_required"}
    if member is None:
        if len(names)==1: member=names[0]
        else:
            result["next_action"]="Specify the exact binary using --member PATH; multiple candidates cannot be guessed"
            return result
    if member not in dict(entries): raise IntakeError("selected member does not exist")
    blob=read_entry(path,kind,member)
    result.update({"status":"analyzed","selected_member":member,
                   "member_sha256":hashlib.sha256(blob).hexdigest(),
                   "analysis":{"slices":analyze_binary(blob,search,at,count)}})
    result["analysis"]["slice_count"]=len(result["analysis"]["slices"])
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description="Read-only Mach-O IPA DEB inspection")
    sub=parser.add_subparsers(dest="action",required=True)
    sub.add_parser("doctor")
    for name in ("inventory","analyze","disasm"):
        p=sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--member")
        p.add_argument("--search",default="")
        p.add_argument("--at",type=lambda x:int(x,0))
        p.add_argument("--count",type=int,default=24)
        p.add_argument("--out")
    a=parser.parse_args(argv)
    if a.action=="doctor": return core.main(["doctor"])
    try:
        if not 1<=a.count<=128: raise IntakeError("count must be 1..128")
        if a.action=="disasm" and a.at is None:
            raise IntakeError("disasm requires --at vmaddr")
        result=inspect(a.file,a.member,a.search[:128],a.at,a.count)
        text=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
        if a.out:
            path=Path(a.out).expanduser()
            if path.is_symlink() or path.exists() or path.resolve()==Path(a.file).resolve():
                raise IntakeError("--out must not overwrite any file")
            path.write_text(text,encoding="utf-8")
        else: print(text,end="")
        return 3 if result.get("status")=="selection_required" else 0
    except (OSError,IntakeError,core.ParseError,struct.error,
            tarfile.TarError,zipfile.BadZipFile,EOFError) as exc:
        print("NO-GO ReverseLab: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
