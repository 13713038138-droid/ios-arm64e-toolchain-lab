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
    "        installBundledSkills()\n        installBundledUltraSkill()\n        installBundledContinuationSkill()\n        migrateMarkBundledSkillsDirty()",
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
recovery_entry = """    // R5.3 upgrade-safe guidance; preserve edited Dev Ultra skills.
    private func installBundledContinuationSkill() {
        let id = "minis-dev-continuation"
        if skills.contains(where: { $0.id == id }) { return }
        guard let overlay = Bundle.main.url(forResource: "default_mount", withExtension: nil) else { return }
        let skillURL = overlay.appendingPathComponent("var/minis/skills/minis-dev-continuation/SKILL.md")
        guard let content = try? String(contentsOf: skillURL, encoding: .utf8) else { return }
        _ = try? importSkill(content: content, source: .bundled)
    }

"""
s = substitute_once(s,
    "    // MARK: - One-time Migration: re-sync skills with bundled files",
    entry + recovery_entry + "    // MARK: - One-time Migration: re-sync skills with bundled files",
    "SkillStore bundled skill")
a = substitute_once(a,
    '        SlashCommand(id: "thinking", icon: "lightbulb", title: "Thinking", subtitle: "Toggle deep thinking mode on/off"),',
    '        SlashCommand(id: "thinking", icon: "lightbulb", title: "Thinking", subtitle: "Toggle deep thinking mode on/off"),\n        SlashCommand(id: "devmax", icon: "hammer.fill", title: "DevMax", subtitle: "Development execution & release gate"),\n        SlashCommand(id: "devcontinue", icon: "arrow.triangle.2.circlepath", title: "Continue Dev", subtitle: "Resume next safe development step"),\n        SlashCommand(id: "devfix", icon: "wrench.and.screwdriver", title: "Explain & Fix", subtitle: "Explain error, choose verified next action"),\n        SlashCommand(id: "devdoctor", icon: "stethoscope", title: "DevDoctor", subtitle: "Diagnose available development tools"),\n        SlashCommand(id: "devtk", icon: "chart.bar.doc.horizontal", title: "DevTK", subtitle: "Audit and reduce token waste with evidence protection"),\n        SlashCommand(id: "devdeb", icon: "shippingbox.fill", title: "Local DEB", subtitle: "Auto-prepare, sign, build and verify a Theos package"),\n        SlashCommand(id: "devabi", icon: "checkmark.seal", title: "R32 ABI v2", subtitle: "Verify source hashes and inspect Apple CI access"),\n        SlashCommand(id: "devnew", icon: "folder.badge.plus", title: "New Dev Project", subtitle: "Scaffold a tweak, UIKit app, CLI or preferences project"),\n        SlashCommand(id: "devhook", icon: "hammer", title: "HookLab", subtitle: "Evidence-first Objective-C hook scaffold"),',
    "slash menu")
a = substitute_once(a,
    '        case "clear":\n            clearChatConfirmRequested = true\n        default:\n            break',
    '        case "devhook":\n            inputText = "/minis-dev-ultra HookLab: verify the target bundle, class, selector and exact method signature from evidence, then scaffold a pass-through Logos hook at a new path. Do not guess ABI or install. If evidence is missing, report it. " + inputText\n            requestComposerFocusSignal.send()\n        case "devnew":\n            inputText = "/minis-dev-ultra Choose tweak, UIKit app, CLI or preferences based on my requirement, then create a new project with minis-dev-ultra new. Use an explicit new output path, validate the bundle id and select the correct RootHide/rootless scheme. Do not overwrite existing files and do not install the resulting package. " + inputText\n            requestComposerFocusSignal.send()\n        case "devmax":\n            inputText = "/minis-dev-ultra " + inputText\n            requestComposerFocusSignal.send()\n        case "devcontinue":\n            inputText = "/minis-dev-ultra CONTINUE the current project, not a new one. Read project source, latest real logs, git status and minis task journal; create a journal if missing, otherwise resume the last verified checkpoint, choose and execute the next bounded safe action, then run tests and save the next checkpoint. Do not just explain or ask me to decide an engineering approach. If blocked by missing access, unknown API/ABI, actual server denial, or required approval, explain simply in Chinese with one next action. Do not modify the stable baseline, do not install or delete apps automatically. " + inputText\n            requestComposerFocusSignal.send()\n        case "devfix":\n            inputText = "/minis-dev-ultra FIX: read and classify the real error. Use minis-dev-ultra assist --error <redacted error text> or --log <existing log path>; never infer an HTTP 400 cause from status alone. Inspect source, reproduce, apply the smallest safe fix and run focused regression, document pass/fail and rollback. For model 400, distinguish account entitlement/model ID from request schema and effort; backup-restored models are not authority. Summarize nontechnically in Chinese; perform the next safe verified step without asking me to invent a solution. " + inputText\n            requestComposerFocusSignal.send()\n        case "devdoctor":\n            inputText = "/minis-dev-ultra Run minis-dev-ultra doctor and report actual compiler/runtime capabilities. " + inputText\n            requestComposerFocusSignal.send()\n        case "devtk":\n            inputText = "/minis-dev-ultra Use the local tk_optimizer.py audit/chat/pack-log/cost tool. Do not claim to bypass provider quotas. Inspect file first, preserve the original. " + inputText\n            requestComposerFocusSignal.send()\n        case "devdeb":\n            inputText = "/minis-dev-ultra Find the active Theos project and run minis-deb auto --project <exact project path> --arch auto. Prepare missing host dependencies when supported, preserve existing project ARCHS and RootHide scheme, use Theos ldid signing, verify DEB metadata, Mach-O architecture slices, LC_CODE_SIGNATURE presence and SHA-256. Do not install the DEB automatically. If the host cannot execute the toolchain or the iPhoneOS SDK is unavailable, report NO-GO and the exact blocker. " + inputText\n            requestComposerFocusSignal.send()\n        case "devabi":\n            inputText = "/minis-dev-ultra Run minis-abi preflight with explicit source archive and candidate DEB paths and expected SHA-256 values, then run minis-abi apple-check for the selected repository. Never upload source or dispatch CI during this read-only check. Report whether private repository access, workflow_dispatch, ABI-v2 markers and the original verifier are confirmed; do not mark ABI v2 accepted without a clean Apple/Xcode run and original verifier evidence. " + inputText\n            requestComposerFocusSignal.send()\n        case "clear":\n            clearChatConfirmRequested = true\n        default:\n            break',
    "slash dispatch")

skill = """---
name: minis-dev-ultra
version: 2.6.0
description: Expert software development engineer. Use for Swift, iOS, SwiftUI, RootHide, arm64e, reverse engineering, local Theos DEB packaging, Apple/Xcode ABI-v2 acceptance, backend, frontend, databases, Python, JavaScript, Go, Rust, AI agents, testing, CI, debugging, security audits and release delivery.
---

# Minis Dev Ultra MAX

Always use actual project files and runtime tools. Work in a source-control branch,
preserve user data and known-good releases, then work in the loop:
inspect -> reproduce -> isolate -> modify -> test -> verify -> package -> document rollback.
Never state that a build, device test or release passed without execution evidence.

## Non-expert continuation and error recovery (R5.3)
The user is not required to know the next engineering step. On "continue", "继续", "please fix", "为什么还没完成", or a bare error, treat it as a request to continue the active project rather than to write a long diagnosis.
1. Inspect actual source, repository revision, task journal, and latest available logs; do not re-ask established project requirements. Never claim access that the runtime lacks.
2. For an error, run minis-dev-ultra assist --error "SANITIZED_ERROR" or minis-dev-ultra assist --log PATH. Classifier output is a hypothesis; confirm against source/runtime before modifying.
3. Choose ONE minimal reversible change; execute with available tools, run relevant focused tests, then regression and build gates. Retry at most twice for the SAME reproduced error without new evidence; never spin on a blocked job.
4. Save stage, test evidence, next step with taskctl.py checkpoint. On interruptions, list/resume a checkpoint. Journal is not a background worker and cannot keep a task running after exit.
5. State in simple Chinese: accomplished, verified evidence, remaining blocker, next action, and whether the user actually must do anything. Explain engineering terms in one sentence. When a needed permission, missing device log, or signed-in account decision is essential, ask ONE precise question, not a choice of technical approaches.
6. Preserve user data, original Minis, source privacy, stable baseline and rollback. Destructive actions, package install, credential changes, and publishing private code require explicit authorization. Never conceal errors or claim that tests passed when not run.

## Model 400 decision gate
A model imported from provider_config.json may appear without validating this client route. HTTP 400 alone is not a diagnosis: inspect sanitized response detail/error.message.
- "not supported when using Codex with a ChatGPT account" means this Codex request path was rejected. If the original Minis with ChatGPT login can actually reply, compare the clients' model ID, endpoint, Version, provider/credential type, account ID hash and non-secret request field names before inferring account entitlement. Do NOT forge an alias, conceal rejection, or treat a header change alone as proof of compatibility.
- Invalid reasoning_effort/field/endpoint: minimize the request, correct only that setting for the verified endpoint, rerun model and tool-call tests. OFF can itself be unsupported for some reasoning models.
- Keep API-key, custom base URL and Codex OAuth separate. Never silently change a saved provider or choose a paid endpoint.
- Without response detail, collect a redacted error or read diagnostic logs; no guessed fix.

## Automatic requirement routing
Before choosing tools or specialist references, run:
minis-dev-ultra route --task "<concise user requirement>" [--path <relevant path> ...]
The router selects primary and supporting engineering profiles, tools, specialist labels, exact selected_references paths and required gates from the request and file extensions. Read the returned selected_references on demand; do not load all 19 references for every task. Do not ask the user to choose a language or tool when the requirement and repository evidence are sufficient. For mixed tasks, combine selected profiles and run the union of their gates. Source evidence may refine the plan; never override contrary source evidence with keyword guesses. The router selects workflows and local tools only; it does not change the AI model, unlock provider quotas or grant permissions. Do not automatically execute destructive or user-data-changing actions without backup, rollback and any required confirmation.
Reuse existing project notes, tests and build infrastructure. Do not invent private APIs.
For local Theos packages, run minis-deb auto --project PATH --arch auto. Let it prepare supported host dependencies, reuse the existing SDK, preserve project architecture and RootHide scheme, use Theos ldid signing, and verify the DEB, Mach-O slices, signature-command presence and SHA-256. Never install a produced package automatically. If the host or SDK is incompatible, report NO-GO instead of claiming success.
For ABI-v2 acceptance, run minis-abi preflight first, then minis-abi apple-check with explicit project paths and expected SHA-256 values. Treat candidates as BUILD_ONLY_NOT_APPLE_VERIFIED until a clean Apple/Xcode run and original verifier evidence are present. Phone Clang 14 output with subtype 0x2 does not pass the ABI-v2 gate. Do not push source or dispatch CI until authenticated access to the selected repository is confirmed, the existing Apple/Xcode workflow and original verifier are inspected, and the exact source archive is staged on a private branch. minis-abi apple-check is read-only; access or workflow inspection is not ABI-v2 acceptance.
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
## HookLab: evidence-first Objective-C hooks
Use minis-dev-ultra hook --name NAME --bundle-id com.example.hook --process com.target.app --class-name VerifiedClass --method '- (BOOL)isEnabled' --path NEW_PATH --scheme roothide only after confirming the exact runtime class and method signature from static/runtime evidence. The generated Logos hook is pass-through only; it preserves the original return/arguments via %orig, never installs itself, and is not proof of runtime compatibility. C-function hooks require a separately proven prototype and ABI and are not generated by this command. Existing output paths are refused.

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
continuation = """---
name: minis-dev-continuation
version: 1.0.0
description: Continue, resume and debug an existing programming or iOS tweak project for a nontechnical user. Trigger when they say 继续, continue, fix it, error 400, cannot compile or do not know next step.
---

# Continue development without making the user design the solution
When a request says "continue", "继续" or gives an error, resume the ACTIVE project using the present chat, real source tree, logs and task journal. Do not start a different project, reset verified baselines, or require the user to choose a compiler/ABI strategy.

1. Identify latest verified source revision, real build result and pending step. First inspect files and python3 /usr/local/lib/minis-dev-ultra/taskctl.py list; if a task exists, read or resume it; otherwise create a project-specific task before changes, then checkpoint every tested milestone. A journal is not an asynchronous agent.
2. Classify the actual error using minis-dev-ultra assist --error "REDACTED_DETAILS" or --log PATH. HTTP 400 alone does not distinguish account restrictions from request parameters. Backup-imported GPT-6.1 entries may display even when this client route fails; a working original app is counterevidence to account-wide ineligibility.
3. Pick the smallest reversible fix and ACT with available tools. Verify project/toolchain/permission, run focused tests and negative controls, then update the checkpoint. Do not repeat a failed attempt unchanged more than twice.
4. If blocked by a missing required source, device log, secret, entitlement or permission, do not speculate or fabricate results. Tell the user the one concrete item you need and why, in plain Chinese. Never ask the user to design technical next steps.
5. End each work phase with: what changed, what actually passed, what did not pass, next action, rollback. A package is only installable if build, signing, hashes and appropriate device tests are verified.
6. Never force-install a tweak, override original Minis/Stheno data, expose tokens, upload private source to a public repository, or bypass vendor model entitlements.

Use minis-dev-ultra skill specialist references for deep engineering details; this skill adds continuation behavior rather than replacing edited user skills.
"""

recovery_path = mount / "var/minis/skills/minis-dev-continuation/SKILL.md"
assert not recovery_path.exists(), "NO-GO: refusing to overwrite existing continuation skill"
recovery_path.parent.mkdir(parents=True, exist_ok=True)
recovery_path.write_text(continuation, encoding="utf-8")

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
    m.write("\n\n## Native offline tools\nUse: minis-dev-ultra doctor|assist|route|new|inspect|triage|scan-secrets|diffzip|manifest|verify-manifest|gate|checkpoint. Use minis-bin for static IPA/DEB/Mach-O inspection, minis-deb auto --project PATH --arch auto for local Theos build/sign/package verification, and minis-abi preflight|apple-check for R32 ABI-v2 source hashes and read-only Apple CI access inspection.\nAll release gate fields must be verified true before claiming an IPA is safe to install.\n")
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
print("PASS: native slash commands + HookLab + bundled skill registration + local DEB factory + R32 ABI-v2 gate + Alpine tools")
print("NO CHANGE: original bundle id, account configuration, Xcode signing, user data")
