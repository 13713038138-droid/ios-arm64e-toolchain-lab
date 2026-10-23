#!/usr/bin/env python3
"""Apply native Minis Dev Ultra MAX integration to pinned OpenMinis.
Fail closed on drift; original app identity, service backends and settings stay unchanged.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: python3 apply_native_max.py /path/to/OpenMinis")
repo = Path(sys.argv[1])
store = repo / "src/ios/Agent/Session/SkillStore.swift"
slash = repo / "src/ios/Agent/Chat/AIChatViewModel+SlashCommands.swift"
mount = repo / "src/ios/default_mount"
assert store.is_file() and slash.is_file() and mount.is_dir(), "NO-GO: unexpected source tree"
s = store.read_text()
a = slash.read_text()

def substitute_once(src, old, new, target):
    assert src.count(old) == 1, f"NO-GO: {target} source drift / double patch"
    return src.replace(old, new, 1)

s = substitute_once(s,
    "        installBundledSkills()\n        migrateMarkBundledSkillsDirty()",
    "        installBundledSkills()\n        installBundledUltraSkill()\n        migrateMarkBundledSkillsDirty()",
    "SkillStore init")
entry = """    // Minis Dev Ultra MAX: bundled professional developer agent.
    private func installBundledUltraSkill() {
        let id = "minis-dev-ultra"
        // Do not overwrite existing user-created or edited skills on launch.
        if skills.contains(where: { $0.id == id }) { return }
        guard let overlay = Bundle.main.url(forResource: "default_mount", withExtension: nil) else { return }
        let skillURL = overlay.appendingPathComponent("var/minis/skills/minis-dev-ultra/SKILL.md")
        guard let content = try? String(contentsOf: skillURL, encoding: .utf8) else { return }
        _ = try? importSkill(content: content, source: .bundled)
    }

"""
s = substitute_once(s,
    "    // MARK: - One-time Migration: re-sync skills with bundled files",
    entry + "    // MARK: - One-time Migration: re-sync skills with bundled files",
    "SkillStore bundled skill")
a = substitute_once(a,
    '        SlashCommand(id: "thinking", icon: "lightbulb", title: "Thinking", subtitle: "Toggle deep thinking mode on/off"),',
    '        SlashCommand(id: "thinking", icon: "lightbulb", title: "Thinking", subtitle: "Toggle deep thinking mode on/off"),\n        SlashCommand(id: "devmax", icon: "hammer.fill", title: "DevMax", subtitle: "Development execution & release gate"),\n        SlashCommand(id: "devdoctor", icon: "stethoscope", title: "DevDoctor", subtitle: "Diagnose available development tools"),\n        SlashCommand(id: "devtk", icon: "chart.bar.doc.horizontal", title: "DevTK", subtitle: "Audit and reduce token waste with evidence protection"),\n        SlashCommand(id: "devdeb", icon: "shippingbox.fill", title: "Local DEB", subtitle: "Auto-prepare, sign, build and verify a Theos package"),\n        SlashCommand(id: "devabi", icon: "checkmark.seal", title: "R32 ABI v2", subtitle: "Verify source hashes and inspect Apple CI access"),\n        SlashCommand(id: "devnew", icon: "folder.badge.plus", title: "New Dev Project", subtitle: "Scaffold a tweak, UIKit app, CLI or preferences project"),',
    "slash menu")
a = substitute_once(a,
    '        case "clear":\n            clearChatConfirmRequested = true\n        default:\n            break',
    '        case "devnew":\n            inputText = "/minis-dev-ultra Choose tweak, UIKit app, CLI or preferences based on my requirement, then create a new project with minis-dev-ultra new. Use an explicit new output path, validate the bundle id and select the correct RootHide/rootless scheme. Do not overwrite existing files and do not install the resulting package. " + inputText\n            requestComposerFocusSignal.send()\n        case "devmax":\n            inputText = "/minis-dev-ultra " + inputText\n            requestComposerFocusSignal.send()\n        case "devdoctor":\n            inputText = "/minis-dev-ultra Run minis-dev-ultra doctor and report actual compiler/runtime capabilities. " + inputText\n            requestComposerFocusSignal.send()\n        case "devtk":\n            inputText = "/minis-dev-ultra Use the local tk_optimizer.py audit/chat/pack-log/cost tool. Do not claim to bypass provider quotas. Inspect file first, preserve the original. " + inputText\n            requestComposerFocusSignal.send()\n        case "devdeb":\n            inputText = "/minis-dev-ultra Find the active Theos project and run minis-deb auto --project <exact project path> --arch auto. Prepare missing host dependencies when supported, preserve the project's existing ARCHS and RootHide scheme, use Theos ldid signing, verify DEB metadata, Mach-O architecture slices, LC_CODE_SIGNATURE presence and SHA-256. Do not install the DEB automatically. If the host cannot execute the toolchain or the iPhoneOS SDK is unavailable, report NO-GO and the exact blocker. " + inputText\n            requestComposerFocusSignal.send()\n        case "devabi":\n            inputText = "/minis-dev-ultra Run minis-abi preflight with the fixed R32 source ZIP and SSH build-only DEB paths and expected SHA-256 values. Then run minis-abi apple-check for Gnn6fvwz78-afk/SthenoBuild and reference run 39485451658. Never upload source or dispatch CI in this read-only check. Report whether private repository access, workflow_dispatch, ABI-v2 markers and the original verifier are confirmed; do not mark ABI v2 accepted without a clean Apple/Xcode run and original verifier evidence. " + inputText\n            requestComposerFocusSignal.send()\n        case "clear":\n            clearChatConfirmRequested = true\n        default:\n            break',
    "slash dispatch")

skill = """---
name: minis-dev-ultra
version: 2.5.0
description: Expert software development engineer. Use for Swift, iOS, SwiftUI, RootHide, arm64e, reverse engineering, local Theos DEB packaging, Apple/Xcode ABI-v2 acceptance, backend, frontend, databases, Python, JavaScript, Go, Rust, AI agents, testing, CI, debugging, security audits and release delivery.
---

# Minis Dev Ultra MAX

Always use actual project files and runtime tools. Work in a source-control branch,
preserve user data and known-good releases, then work in the loop:
inspect -> reproduce -> isolate -> modify -> test -> verify -> package -> document rollback.
Never state that a build, device test or release passed without execution evidence.

## Automatic requirement routing
Before choosing tools or specialist references, run:
minis-dev-ultra route --task "<concise user requirement>" [--path <relevant path> ...]
The router selects primary and supporting engineering profiles, tools, specialist labels, exact selected_references paths and required gates from the request and file extensions. Read the returned selected_references on demand; do not load all 19 references for every task. Do not ask the user to choose a language or tool when the requirement and repository evidence are sufficient. For mixed tasks, combine selected profiles and run the union of their gates. Source evidence may refine the plan; never override contrary source evidence with keyword guesses. The router selects workflows and local tools only; it does not change the AI model, unlock provider quotas or grant permissions. Do not automatically execute destructive or user-data-changing actions without backup, rollback and any required confirmation.
Reuse existing project notes, tests and build infrastructure. Do not invent private APIs.
For local Theos packages, run minis-deb auto --project PATH --arch auto. Let it prepare supported host dependencies, reuse the existing SDK, preserve project architecture and RootHide scheme, use Theos ldid signing, and verify the DEB, Mach-O slices, signature-command presence and SHA-256. Never install a produced package automatically. If the host or SDK is incompatible, report NO-GO instead of claiming success.
For R32 ABI-v2 acceptance, run minis-abi preflight first, then minis-abi apple-check. The source ZIP SHA-256 must match 081e7cea8f85c88de68f540adb98f4862f21de950db20e8219a90e765ee6ec33 and the existing SSH candidate DEB must match fdf8dd2fd50ec652bbd11942b23baa2d5fa0564be53a6251aba605e4fc1bd5eb. Treat the candidate as BUILD_ONLY_NOT_APPLE_VERIFIED. Phone Clang 14 output with subtype 0x2 does not pass the ABI-v2 gate. Do not push source or dispatch CI until authenticated access to Gnn6fvwz78-afk/SthenoBuild is confirmed, the existing Apple/Xcode workflow and original verifier are inspected, and the exact source archive is staged on a private branch. minis-abi apple-check is read-only; access or workflow inspection is not ABI-v2 acceptance.
On iOS/Mach-O, confirm slices, dyld symbols, PAC/ABI calling conventions, ownership,
scene/card/keyboard write authorities and running process identity.
For a RootHide package check rootless scheme, arm64e ABI, entitlements, install paths,
hashes, dependencies and rollback.
For all languages use minimal diffs, compile and lint checks, regression tests,
performance profiling, dependency audits and secret scanning where the tools exist.
No false multi-agent claims: if real parallel delegations exist, divide into independent
analysis, implementation, adversarial review, and release checks. Otherwise run
these passes sequentially and label them accurately.
Summarize after each significant milestone: baseline hash, changed files, commands
actually executed, exact results, remaining blockers, final artifact or NO-GO.
Never delete/replace App Store application data without a verifiable backup.
## Resumable task journal\nUse `python3 /usr/local/lib/minis-dev-ultra/taskctl.py create --title "..." --project PATH` before multi-stage work. Record a checkpoint after each milestone; on interruption, use `list`, `show ID`, and `resume ID` to continue from the saved next step. It redacts common token patterns and stores append-only events. It records recovery state only; it does not execute commands or guarantee process survival across app exit/respring.\n\n## Apelin-inspired developer workflow (R5 parity layer)
The public Apelin project is MIT-licensed; use its documented feature set as an architectural reference, not as proof that its separate app/daemon already exists inside Minis. R5 routes on-device IDE, compiler/SDK lifecycle, terminal persistence, install diagnostics, approval policy, project templates, Git/transfer and disassembly-tool requests to dedicated workflows.
Create new Theos projects only at an explicit new path with:
minis-dev-ultra new --kind tweak|app|cli|preferences --name NAME --bundle-id com.example.name --path NEW_PATH --scheme roothide|rootless
The scaffold refuses existing output paths, chooses a scheme-matching architecture, and does not install the generated package. Then run minis-deb doctor and minis-deb auto --project PATH --arch auto; inspect the report, DEB metadata, Mach-O slices, signature-command presence and SHA-256.
Do not claim full Apelin parity yet: native multi-file IDE/editor UI, on-device Apple CLT/iPhoneOS SDK manager, daemon-backed persistent terminal/job resumption, privileged install daemon and authenticated IPC, post-respring load-marker watcher, crash symbolication/UI tree/actions, project/toolchain transfer manager, and bundled Capstone/Keystone extensions remain unported until implemented and tested. If a capability is missing, say so and use an authorized fallback rather than inventing a command.
Before package install, respring, privileged action, credential change or destructive edit, show the planned action and obtain required approval; never expose tokens in logs. Preserve the original Minis app identity and user data, and keep R5 as a separate test identity.
When a model, CI, Xcode, signing identity or network is absent, say unavailable,
do not fabricate functionality or a signed IPA.
"""

runtime_dir = Path(__file__).parent / "runtime"
doctor = (runtime_dir / "minis-dev-ultra").read_text(encoding="utf-8")
cli = mount / "usr/local/bin/minis-dev-ultra"
mainskill = mount / "var/minis/skills/minis-dev-ultra/SKILL.md"
assert not cli.exists() and not mainskill.exists(), "NO-GO: refusing to replace preexisting resources"
for path in [cli, mainskill]:
    path.parent.mkdir(parents=True, exist_ok=True)
cli.write_text(doctor)
cli.chmod(0o755)
mainskill.write_text(skill)
import shutil
extra = repo / "src/ios/default_mount/usr/local/lib/minis-dev-ultra/devctl.py"
extra.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(__file__).with_name("devctl.py"), extra)
extra.chmod(0o644)
task_journal = extra.with_name("taskctl.py")
assert not task_journal.exists(), "NO-GO: refusing to overwrite preexisting task journal"
shutil.copy2(Path(__file__).with_name("taskctl.py"), task_journal)
task_journal.chmod(0o644)
deb_factory = extra.with_name("deb_factory.py")
assert not deb_factory.exists(), "NO-GO: refusing to overwrite preexisting local DEB factory"
shutil.copy2(Path(__file__).with_name("deb_factory.py"), deb_factory)
deb_factory.chmod(0o644)
abi_gate = extra.with_name("abi_v2_gate.py")
assert not abi_gate.exists(), "NO-GO: refusing to overwrite preexisting ABI-v2 gate"
shutil.copy2(Path(__file__).with_name("abi_v2_gate.py"), abi_gate)
abi_gate.chmod(0o644)
tk = extra.with_name("tk_optimizer.py")
shutil.copy2(Path(__file__).with_name("tk_optimizer.py"), tk)
tk.chmod(0o644)
tool_targets = [
    (runtime_dir / "ensure-python3.sh", extra.parent / "ensure-python3.sh", 0o755),
    (runtime_dir / "minis-bin", mount / "usr/local/bin/minis-bin", 0o755),
    (runtime_dir / "minis-tk", mount / "usr/local/bin/minis-tk", 0o755),
    (runtime_dir / "minis-deb", mount / "usr/local/bin/minis-deb", 0o755),
    (runtime_dir / "minis-abi", mount / "usr/local/bin/minis-abi", 0o755),
]
for source, target, mode in tool_targets:
    if not source.is_file():
        raise RuntimeError("NO-GO: missing runtime wrapper " + str(source))
    if target.exists():
        raise RuntimeError("NO-GO: refusing to overwrite pre-existing tool " + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(mode)
with mainskill.open("a", encoding="utf-8") as m:
    m.write("\n\n## Native offline tools\nUse: minis-dev-ultra doctor|route|new|inspect|triage|scan-secrets|diffzip|manifest|verify-manifest|gate|checkpoint. Use minis-bin for static IPA/DEB/Mach-O inspection, minis-deb auto --project PATH --arch auto for local Theos build/sign/package verification, and minis-abi preflight|apple-check for R32 ABI-v2 source hashes and read-only Apple CI access inspection.\nAll release gate fields must be verified true before claiming an IPA is safe to install.\n")
# Bundle independent specialist references; they are loaded only when needed.
ref_source = Path(__file__).parent / "references"
ref_target = mainskill.parent / "references"
refs = sorted(ref_source.glob("*.md"))
if len(refs) != 19:
    raise RuntimeError("NO-GO: expected exactly 19 specialist references")
ref_target.mkdir(parents=True, exist_ok=True)
for item in refs:
    shutil.copy2(item, ref_target / item.name)
with mainskill.open("a", encoding="utf-8") as m:
    m.write("\n## Specialist references (load on demand)\n")
    for item in refs:
        m.write("- references/" + item.name + "\n")

with mainskill.open("a", encoding="utf-8") as m:
    m.write("\n## Token savings and provider limits\nUse minis-tk audit <file>, minis-tk chat <jsonl>, minis-tk pack-log <file> --out <copy> --budget <tokens>, or minis-tk cost with caller-provided rates. Estimates are approximate, not provider billing. Keep source logs intact.\nThe upstream app already has cache, context compaction, and model-group routing; use them first instead of new conflicting hooks. Model quotas and server limits cannot be unlocked locally.\n")
store.write_text(s)
slash.write_text(a)
print("PASS: native slash commands + bundled skill registration + local DEB factory + R32 ABI-v2 gate + Alpine tools")
print("NO CHANGE: original bundle id, account configuration, Xcode signing, user data")
