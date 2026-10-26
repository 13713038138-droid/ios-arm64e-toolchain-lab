#!/usr/bin/env python3
"""Integrate R60 native suite AFTER proven R59 native overlay (strict anchors)."""
from pathlib import Path
import json
import shutil
import sys

DESCRIPTION = """
## R60 integrated native development tools — Apelin App is NOT required
- minis-native doctor: read-only, actual binary/SDK path inventory with
  conservative compatibility markers (presence != execution/runtime support).
- minis-native triage local.ips [--binary matching-MachO]: Apple IPS crash,
  jetsam 210, panic 109, hang 298 and resource 288 classification; crash
  frames symbolicated only when Mach-O LC_UUID matches. Non-crash reports
  are NOT misreported as EXC_BAD_ACCESS.
- minis-native macho file: delegate to existing bounded ReverseLab analysis.
- minis-native ipa-gate file.ipa --expected-id com.openminis.devultramax.r60:
  static ZIP identity/embedded tool/license/old-bridge inspection. This gate
  DOES NOT cryptographically verify codesign or prove device compatibility.
- Keep existing minis-crash, minis-reverse, minis-deb, minis-engineer,
  devctl, backup/recovery, Theos, Swift and ARM64e tools. No duplicate
  backend, no privileged helper, no system-state changes.
- No Apelin executable, daemon or app is necessary. Some Apelin features
  require unavailable jailbreak entitlements or independent engineering;
  never pretend this is full Apelin IDE or live device UI automation.
Attribution: OwnGoal Studio MIT IPSDecoder and crash analysis design,
license file at /usr/local/lib/minis-dev-ultra/native_diagnostics_LICENSE.txt.
"""
WRAPPER = '''#!/bin/sh
set -eu
. /usr/local/lib/minis-dev-ultra/ensure-python3.sh
ensure_python3
exec python3 /usr/local/lib/minis-dev-ultra/native_suite.py "$@"
'''

def substitute_once(source,old,new,label):
    if source.count(old)!=1:
        raise ValueError("NO-GO source drift in "+label+": "+str(source.count(old)))
    return source.replace(old,new,1)

def integrate(repo):
    root=Path(repo)
    app=root/"src/ios"
    mount=app/"default_mount"
    swift=app/"Agent/Chat/AIChatViewModel+SlashCommands.swift"
    sources=Path(__file__).parent
    source=sources/"native_suite_r60.py"
    target=mount/"usr/local/lib/minis-dev-ultra/native_suite.py"
    wrapper=mount/"usr/local/bin/minis-native"
    skills=[mount/"var/minis/skills/minis-dev-ultra/SKILL.md",
            mount/"var/minis/skills/minis-dev-autopilot/SKILL.md"]
    for f in [swift,source,*skills,mount/"usr/local/bin/minis-crash",
              mount/"usr/local/lib/minis-dev-ultra/native_crash.py",
              mount/"usr/local/lib/minis-dev-ultra/reverse_lab.py",
              mount/"usr/local/lib/minis-dev-ultra/native_diagnostics_LICENSE.txt",
              mount/"usr/local/lib/minis-dev-ultra/ensure-python3.sh"]:
        if not f.is_file():raise ValueError("NO-GO missing R59 baseline: "+str(f))
    for f in [target,wrapper,mount/"usr/local/bin/minis-apelin",
              mount/"usr/local/lib/minis-dev-ultra/apelin_bridge.py"]:
        if f.exists() or f.is_symlink():raise ValueError("NO-GO unexpected existing bridge/tool: "+str(f))
    s=swift.read_text(encoding="utf8")
    old='R5.9 offline diagnostics option: when given a crash IPS and the binary, use minis-crash for evidence and UUID-gated symbol resolution; no Apelin app or daemon. Do not claim source lines or live crash access without evidence.'
    new=('R60 integrated native tool suite: use minis-native doctor for SDK/compiler inventory, '
         'minis-native triage for existing crash/jetsam/panic/resource/hang IPS, '
         'minis-native macho for read-only ReverseLab analysis, and minis-native ipa-gate '
         'for static release provenance. Use existing minis-crash, Theos, minis-deb and '
         'bounded engineer checkpoint tools for their original functions. '
         'No Apelin App, daemon, install, respring or automatic privileges. '
         'Tool presence does not prove runtime or device acceptance.')
    s=substitute_once(s,old,new,"R59 native auto integration")
    # Do not add another slash command. One existing Auto Engineer is the entry.
    if 'case "devauto"' not in s or 'case "devcrash"' not in s:
        raise ValueError("NO-GO existing slash entries not found")
    for f in skills:
        if "R60 integrated native development tools" in f.read_text(encoding="utf8"):
            raise ValueError("NO-GO already patched")
    shutil.copy2(source,target)
    wrapper.write_text(WRAPPER,encoding="utf8");wrapper.chmod(0o755)
    swift.write_text(s,encoding="utf8")
    for f in skills:
        with f.open("a",encoding="utf8") as dest:dest.write("\n"+DESCRIPTION+"\n")
    return {"native_command":"minis-native","auto_engineer_preserved":True,
            "old_bridge_present":False,"device_verified":False}

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: apply_native_suite_r60.py /path/to/OpenMinis")
    try:print(json.dumps(integrate(sys.argv[1]),ensure_ascii=False,indent=2))
    except (OSError,ValueError) as e:
        print(str(e),file=sys.stderr);sys.exit(2)
