#!/usr/bin/env python3
"""R5.9 native offline crash diagnostics. Apply after R5.7 native/adaptive patches.

R5.8's external Apelin bridge is deliberately NOT applied to this build.
"""
from pathlib import Path
import json, shutil, sys
NOTE="""
## Native iOS Crash Diagnostics (Apelin-derived, no Apelin installation)
Run: minis-crash /path/to/report.ips --binary /path/to/exact-UUID-MachO --out /path/to/new-result.json
only for files you are authorized to inspect. Parser is read-only; only explicit
--out creates a new JSON file. It parses Apple IPS JSON crash threads, image
UUID and imageOffset, inspects arm64/arm64e Mach-O symbols, and refuses
symbolication unless image UUID matches. Function boundaries from
LC_FUNCTION_STARTS prevent attribution to an adjacent stripped function.
Do NOT claim DWARF source lines, full Apelin IDE, daemon, live crash capture,
device verification or automatic source repair. Tool gives evidence to the
model; independently establish root cause, exact PAC ABI and regression passes.
MIT attribution: native_diagnostics_LICENSE.txt and
https://github.com/owngoal-dev/Apelin (OwnGoal Studio).
"""
WRAPPER='''#!/bin/sh
set -eu
. /usr/local/lib/minis-dev-ultra/ensure-python3.sh
ensure_python3
exec python3 /usr/local/lib/minis-dev-ultra/native_crash.py "$@"
'''
def replace_one(text,old,new,gate):
    if text.count(old)!=1:raise RuntimeError('NO-GO source drift '+gate)
    return text.replace(old,new,1)
def integrate(repo):
    base=Path(repo)
    m=base/'src/ios/default_mount'
    swift=base/'src/ios/Agent/Chat/AIChatViewModel+SlashCommands.swift'
    source=Path(__file__).with_name('minis_native_crash_r59.py')
    license_source=Path(__file__).with_name('native_diagnostics_LICENSE.txt')
    output=m/'usr/local/lib/minis-dev-ultra/native_crash.py'
    license_dest=m/'usr/local/lib/minis-dev-ultra/native_diagnostics_LICENSE.txt'
    wrapper=m/'usr/local/bin/minis-crash'
    skills=[m/'var/minis/skills/minis-dev-ultra/SKILL.md',
            m/'var/minis/skills/minis-dev-autopilot/SKILL.md']
    for path in (swift,source,license_source,*skills,
                 m/'usr/local/lib/minis-dev-ultra/ensure-python3.sh'):
        if not path.is_file():raise RuntimeError('NO-GO missing baseline '+str(path))
    for path in (output,license_dest,wrapper,
                 m/'usr/local/lib/minis-dev-ultra/apelin_bridge.py',
                 m/'usr/local/bin/minis-apelin'):
        if path.exists() or path.is_symlink():
            raise RuntimeError('NO-GO stale bridge or existing destination '+str(path))
    s=swift.read_text('utf8')
    if 'devapelin' in s:raise RuntimeError('NO-GO external bridge already integrated')
    s=replace_one(s,'        SlashCommand(id: "devauto",',
        '        SlashCommand(id: "devcrash", icon: "waveform.path.ecg", title: "Native Crash", subtitle: "Offline Apple IPS crash and UUID-matched Mach-O symbol diagnosis"),\n        SlashCommand(id: "devauto",',
        'menu')
    s=replace_one(s,'        case "devauto":',
        '        case "devcrash":\n'
        '            inputText = "/minis-dev-ultra Native Crash: If the user provided .ips/.macho, run minis-crash with --binary evidence (matching UUID). Analyze the real faulting thread and precise symbol offsets; never invent ABI, source lines, live injection, or tool output. This tool needs no Apelin installation. " + inputText\n'
        '            requestComposerFocusSignal.send()\n'
        '        case "devauto":','dispatch')
    s=replace_one(s,'        case "devauto":\n',
        '        case "devauto":\n'
        '            inputText = "R5.9 offline diagnostics option: when given a crash IPS and the binary, use minis-crash for evidence and UUID-gated symbol resolution; no Apelin app or daemon. Do not claim source lines or live crash access without evidence. " + inputText\n',
        'auto engineering')
    shutil.copy2(source,output)
    shutil.copy2(license_source,license_dest)
    wrapper.write_text(WRAPPER,encoding='utf8');wrapper.chmod(0o755)
    swift.write_text(s,encoding='utf8')
    for path in skills:
        with path.open('a',encoding='utf8') as f:f.write('\n'+NOTE+'\n')
    return dict(mode='offline_native',no_external_apelin=True,device_verified=False)
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: apply_native_r59.py /path/to/OpenMinis')
    try:print(json.dumps(integrate(sys.argv[1]),indent=2))
    except (OSError,RuntimeError) as e:
        print(str(e),file=sys.stderr);raise SystemExit(2)
