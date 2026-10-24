#!/usr/bin/env python3
"""Optional REAL LLVM ARM64 Mach-O disassembly for Minis ReverseLab.

Uses existing llvm-objdump, with subprocess argv (no shell), size/time/output
limits and a temporary Mach-O slice automatically removed after parsing.
Never runs analyzed code or mutates user inputs.
"""
import os
import re
import shutil
import subprocess
import tempfile

MAX_DISASM_BYTES=64*1024*1024
MAX_OUTPUT=512*1024
LINE=re.compile(r"^\s*([0-9a-fA-F]{1,16}):\s+([0-9a-fA-F]{8})\s+([a-zA-Z][a-zA-Z0-9_.]*)\s*(.*?)\s*$")

def executable():
    # Use a real executable on this host. Do not download or pip-install
    # anything or claim Capstone/LLVM when not installed.
    return shutil.which("llvm-objdump")

def decode(data, start, length, address, count):
    """Return (instructions, problem). Empty result means NOT verified."""
    exe=executable()
    if not exe:
        return [], "llvm-objdump is not installed"
    if length<32 or length>MAX_DISASM_BYTES:
        return [], "Mach-O slice exceeds bounded native disassembly size"
    if count < 1 or count > 128 or address < 0:
        return [], "invalid disassembly range"
    if start < 0 or length > len(data)-start:
        return [], "invalid Mach-O slice range"
    filename=None
    try:
        with tempfile.NamedTemporaryFile(prefix="minis-reverse-",suffix=".macho",delete=False) as output:
            filename=output.name
            os.chmod(filename,0o600)
            output.write(data[start:start+length])
        cmd=[exe,"--disassemble","--start-address=0x%x"%address,
             "--stop-address=0x%x"%(address+count*4),filename]
        outcome=subprocess.run(cmd,capture_output=True,timeout=9,check=False)
        if outcome.returncode:
            return [], "llvm-objdump rejected this Mach-O slice"
        if len(outcome.stdout)>MAX_OUTPUT:
            return [], "llvm-objdump result exceeds output bound"
        result=[]
        for row in outcome.stdout.decode("utf-8","replace").splitlines():
            match=LINE.match(row)
            if not match: continue
            pc=int(match.group(1),16)
            if pc<address or pc>=address+count*4: continue
            result.append({"address":f"0x{pc:x}","mnemonic":match.group(3),
                          "operands":match.group(4)})
            if len(result)>=count: break
        if not result:
            return [], "llvm-objdump returned no parsed ARM64 instructions"
        return result,None
    except (OSError,subprocess.TimeoutExpired):
        return [], "llvm-objdump failed or exceeded the time limit"
    finally:
        if filename:
            try: os.unlink(filename)
            except FileNotFoundError: pass
