#!/usr/bin/env python3
"""Install R5.9 standalone offline crash analyzer after proven R5.7 overlay."""
from pathlib import Path
import json, shutil, sys
ADVICE="""
## R5.9 native offline crash analysis (without Apelin app)
Run minis-crash /path/to/report.ips --binary /path/to/matching.dylib
or repeat --binary for matching dSYM DWARF Mach-O. Static symbols only.
Exact LC_UUID match mandatory; unknown/stripped functions remain unknown.
No DWARF line decoding, daemon, Apelin Console, install, hook or respring.
Python 3 stdlib; continue using stable Theos arm64e PAC ABI 0 tools.
MIT-adapted OwnGoal Studio diagnostics; license bundled with executable.
"""
WRAPPER='''#!/bin/sh
set -eu
. /usr/local/lib/minis-dev-ultra/ensure-python3.sh
ensure_python3
exec python3 /usr/local/lib/minis-dev-ultra/native_crash.py "$@"
'''
def once(src,old,new,label):
    if src.count(old)!=1:raise RuntimeError("NO-GO source drift: "+label)
    return src.replace(old,new,1)
def install(repo):
    root=Path(repo)
    m=root/"src/ios/default_mount"
    swift=root/"src/ios/Agent/Chat/AIChatViewModel+SlashCommands.swift"
    skill=m/"var/minis/skills/minis-dev-ultra/SKILL.md"
    auto=m/"var/minis/skills/minis-dev-autopilot/SKILL.md"
    source=Path(__file__).parent
    copies=[(source/"native_crash_r59.py",m/"usr/local/lib/minis-dev-ultra/native_crash.py"),
            (source/"native_diagnostics_LICENSE.txt",m/"usr/local/lib/minis-dev-ultra/native_diagnostics_LICENSE.txt")]
    wrapper=m/"usr/local/bin/minis-crash"
    for p in [swift,skill,auto,m/"usr/local/lib/minis-dev-ultra/ensure-python3.sh"]+[a for a,b in copies]:
        if not p.is_file():raise RuntimeError("NO-GO missing source: "+str(p))
    for a,b in copies:
        if b.exists() or b.is_symlink():raise RuntimeError("NO-GO already installed")
    if wrapper.exists():raise RuntimeError("NO-GO wrapper already installed")
    if (m/"usr/local/bin/minis-apelin").exists() or (m/"usr/local/lib/minis-dev-ultra/apelin_bridge.py").exists():
        raise RuntimeError("NO-GO old external bridge still bundled")
    s=swift.read_text(encoding="utf-8")
    s=once(s,'        SlashCommand(id: "devauto",',
        '        SlashCommand(id: "devcrash", icon: "ant", title: "Crash Doctor", subtitle: "Offline IPS and UUID-verified symbols"),\n        SlashCommand(id: "devauto",',
        "slash menu")
    s=once(s,'        case "devauto":',
        '        case "devcrash":\n'
        '            inputText = "/minis-dev-ultra Offline Crash Doctor: use minis-crash on a local IPS and matching UUID Mach-O or dSYM. Never guess symbols or install. Apelin App is not required. " + inputText\n'
        '            requestComposerFocusSignal.send()\n'
        '        case "devauto":',
        "slash dispatch")
    s=once(s,'        case "devauto":\n',
        '        case "devauto":\n'
        '            inputText = "R5.9 native diagnostics: use bundled minis-crash for an IPS report, match LC_UUID before symbolication. Do not use /devapelin or the external Apelin Console. If data is missing, report uncertainty. " + inputText\n',
        "auto engineer")
    for a,b in copies:shutil.copy2(a,b)
    wrapper.write_text(WRAPPER,encoding="utf-8");wrapper.chmod(0o755)
    swift.write_text(s,encoding="utf-8")
    for p in (skill,auto):
        with p.open("a",encoding="utf-8") as f:f.write("\n"+ADVICE+"\n")
    return {"built_in":"minis-crash","slash_command":"/devcrash",
            "apelin_app_required":False,"device_verified":False}
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: apply_native_apelin_r59.py /path/to/OpenMinis")
    try:print(json.dumps(install(sys.argv[1]),ensure_ascii=False,indent=2))
    except (OSError,RuntimeError) as e:print(e,file=sys.stderr);raise SystemExit(2)
