#!/usr/bin/env python3
"""Offline developer diagnostics for Minis Dev Ultra MAX.
Read-only by default. Any writes require explicit --out path. Stdlib only.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import plistlib
import re
import shutil
import struct
import sys
import tempfile
import zipfile

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def emit(data, output=None):
    raw = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        p = pathlib.Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(raw, encoding="utf-8")
        print("WROTE", p)
    else:
        print(raw, end="")

def architecture_name(cpu, subtype):
    cpu = cpu & 0xffffffff
    subtype = subtype & 0xffffffff
    base_subtype = subtype & 0xff
    if cpu == 0x0100000c:
        return "arm64e" if base_subtype == 2 else "arm64"
    if cpu == 0x01000007:
        return "x86_64"
    if cpu == 12:
        return "arm"
    if cpu == 7:
        return "i386"
    if cpu == 18:
        return "ppc"
    if cpu == 0x01000012:
        return "arm64_32"
    return "cpu_%08x_subtype_%08x" % (cpu, subtype)

def macho_header(raw):
    if len(raw) < 32:
        return {"kind": "unknown", "reason": "truncated header"}
    if struct.unpack_from("<I", raw)[0] == 0xfeedfacf:
        magic, cpu, subtype, ftype, count, cmd_bytes, flags, reserved = struct.unpack_from("<IiiIIIII", raw)
        if count > 4096 or cmd_bytes > 8 * 1024 * 1024 or cmd_bytes + 32 > len(raw):
            return {"kind": "macho64", "error": "truncated or implausible load commands"}
        pos, cryptid = 32, None
        for _ in range(count):
            if pos + 8 > len(raw):
                break
            cmd, length = struct.unpack_from("<II", raw, pos)
            if length < 8 or pos + length > len(raw):
                break
            if cmd in (0x21, 0x2c) and length >= 20:
                cryptid = struct.unpack_from("<I", raw, pos + 16)[0]
            pos += length
        return {"kind": "macho64", "cpu": cpu, "subtype": subtype & 0xffffffff,
                "architecture": architecture_name(cpu, subtype),
                "cryptid": cryptid, "load_commands": count}
    if struct.unpack_from(">I", raw)[0] in (0xcafebabe, 0xcafebabf):
        return {"kind": "fat-macho", "note": "inspect all slices independently"}
    return {"kind": "unknown", "magic": raw[:4].hex()}

def inspect_macho_file(path):
    size = pathlib.Path(path).stat().st_size
    with open(path, "rb") as stream:
        magic = stream.read(4)
        magic_value = int.from_bytes(magic, "big")
        if magic_value not in (0xcafebabe, 0xcafebabf):
            stream.seek(0)
            return macho_header(stream.read(8 * 1024 * 1024))
        stream.seek(0)
        fat_header = stream.read(8)
        if len(fat_header) != 8:
            return {"kind": "fat-macho", "error": "truncated universal header"}
        magic_value, count = struct.unpack(">II", fat_header)
        is64 = magic_value == 0xcafebabf
        entry_size = 32 if is64 else 20
        if count < 1 or count > 64:
            return {"kind": "fat-macho", "error": "implausible slice count", "slice_count": count}
        table = stream.read(count * entry_size)
        if len(table) != count * entry_size:
            return {"kind": "fat-macho", "error": "truncated architecture table", "slice_count": count}
        table_end = 8 + len(table)
        slices = []
        for index in range(count):
            entry = table[index * entry_size:(index + 1) * entry_size]
            if is64:
                cpu, subtype, offset, slice_size, align, reserved = struct.unpack(">iiQQII", entry)
            else:
                cpu, subtype, offset, slice_size, align = struct.unpack(">iiIII", entry)
            item = {"index": index, "architecture": architecture_name(cpu, subtype),
                    "cpu": cpu & 0xffffffff, "subtype": subtype & 0xffffffff,
                    "offset": offset, "size": slice_size, "align": align}
            if offset < table_end or slice_size < 32 or offset + slice_size > size:
                item["error"] = "slice range is outside the file or overlaps its table"
            else:
                stream.seek(offset)
                item["header"] = macho_header(stream.read(min(slice_size, 8 * 1024 * 1024)))
            slices.append(item)
        return {"kind": "fat-macho", "size": size, "slice_count": count, "slices": slices}

def cmd_inspect(args):
    p = pathlib.Path(args.path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    data = {"file": str(p), "size": p.stat().st_size, "sha256": sha256(p)}
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            entries = z.infolist()
            data["kind"] = "zip"
            data["entries"] = len(entries)
            data["expanded_bytes"] = sum(x.file_size for x in entries)
            paths = [x.filename for x in entries]
            data["dangerous_member_names"] = [name for name in paths if
                                               name.startswith("/") or ".." in pathlib.PurePosixPath(name).parts][:20]
            if p.suffix.lower() == ".ipa":
                data["kind"] = "ipa"
                matches = [name for name in paths if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", name)]
                if matches:
                    root = matches[0][:-len("Info.plist")]
                    meta = plistlib.loads(z.read(matches[0]))
                    for key in ("CFBundleIdentifier", "CFBundleVersion", "CFBundleShortVersionString", "MinimumOSVersion"):
                        data[key] = meta.get(key)
                    binary = root + str(meta.get("CFBundleExecutable", ""))
                    if binary in paths:
                        with z.open(binary) as src:
                            data["executable"] = macho_header(src.read(9 * 1024 * 1024))
                    data["extensions"] = len([x for x in paths if x.endswith(".appex/Info.plist")])
                else:
                    data["warning"] = "missing main app metadata"
    elif p.suffix.lower() in (".dylib", ".bin", ""):
        data.update(inspect_macho_file(p))
    elif p.suffix.lower() == ".deb":
        with p.open("rb") as f:
            data["kind"] = "deb" if f.read(8) == b"!<arch>\n" else "not-deb"
        data["note"] = "No installer scripts executed"
    else:
        data["kind"] = "unknown"
    emit(data, args.out)

CATEGORIES = {
    "build": r"(?i)\berror:|fatal error|undefined symbols|ld: |linker command failed|BUILD FAILED",
    "crash": r"(?i)EXC_BAD_ACCESS|SIGSEGV|SIGABRT|crash|terminating app",
    "memory": r"(?i)Jetsam|memory pressure|Killed:\s*9|EXC_RESOURCE",
    "keyboard": r"(?i)keyboardWill(Show|Hide)|UIInputSet|firstResponder|keyboard.*(restore|expand)",
    "orientation": r"(?i)orientation|rotate|landscape|portrait",
    "gesture": r"(?i)hitTest|pointInside|touchesBegan|UIStatusBarWindow|gesture",
    "ownership": r"(?i)swift_retain|shared_ptr|releaseOnce|use.after.free|owner|CAS|lease",
}
def cmd_triage(args):
    patterns = {k: re.compile(v) for k, v in CATEGORIES.items()}
    hits = {k: [] for k in patterns}
    with open(args.path, encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            for group, pattern in patterns.items():
                if len(hits[group]) < args.limit and pattern.search(line):
                    hits[group].append({"line": line_no, "text": line.strip()[:240]})
    emit({"file": args.path, "hits": hits, "note": "Matches are clues, not causal proof"}, args.out)

SECRET_PATTERNS = {
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
}
SKIP = {".git", "node_modules", "build", ".build", "DerivedData", "__pycache__", ".venv"}
TEXT = {".swift", ".m", ".mm", ".h", ".py", ".sh", ".js", ".ts", ".tsx",
        ".json", ".md", ".txt", ".yml", ".yaml", ".plist", ".env", ".xml", ".go", ".rs"}
def cmd_secrets(args):
    root = pathlib.Path(args.path)
    candidates = [root] if root.is_file() else (p for p in root.rglob("*") if p.is_file())
    findings = []
    scanned = 0
    for p in candidates:
        if any(part in SKIP for part in p.parts) or (p.suffix not in TEXT and p.name != ".env"):
            continue
        if p.stat().st_size > 1024 * 1024:
            continue
        scanned += 1
        for number, line in enumerate(p.read_text("utf-8", errors="replace").splitlines(), 1):
            for kind, pat in SECRET_PATTERNS.items():
                if pat.search(line):
                    findings.append({"path": str(p), "line": number, "kind": kind})
    emit({"scanned_files": scanned, "potential_findings": findings,
          "note": "Values redacted; scanners cannot prove absence of secrets"}, args.out)

def cmd_doctor(args):
    tools = ["sh", "python3", "git", "swift", "clang", "xcodebuild", "codesign",
             "ldid", "dpkg-deb", "otool", "nm", "make", "cmake", "node", "npm", "go", "rustc"]
    emit({"version": "2.1.0", "platform": sys.platform,
          "executables": {name: shutil.which(name) for name in tools},
          "warning": "Presence does not establish iOS signing or architecture compatibility"}, args.out)

def cmd_diff(args):
    def members(path):
        with zipfile.ZipFile(path) as z:
            return {f.filename: (f.file_size, f.CRC) for f in z.infolist() if not f.is_dir()}
    a, b = members(args.old), members(args.new)
    emit({"added": sorted(b.keys() - a.keys()),
          "removed": sorted(a.keys() - b.keys()),
          "changed": sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
          "note": "CRC and size prefilter only, verify SHA256 for release assets"}, args.out)

def cmd_manifest(args):
    root = pathlib.Path(args.path).resolve()
    out = pathlib.Path(args.out).resolve()
    if not root.is_dir():
        raise ValueError("input must be a directory")
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.resolve() != out and ".git" not in p.parts:
            rows.append(sha256(p) + "  " + p.relative_to(root).as_posix())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("WROTE", out, "files", len(rows))

def cmd_verify(args):
    base = pathlib.Path(args.root).resolve()
    errors = []
    n = 0
    for line in pathlib.Path(args.path).read_text().splitlines():
        if not line.strip():
            continue
        found = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        if not found:
            errors.append("invalid manifest row")
            continue
        want, name = found.groups()
        target = (base / name).resolve()
        if not target.is_relative_to(base) or not target.is_file() or sha256(target) != want.lower():
            errors.append(name)
        n += 1
    emit({"verified": n, "mismatches": errors, "status": "PASS" if not errors else "NO-GO"}, args.out)
    if errors:
        sys.exit(1)

def cmd_gate(args):
    checks = json.loads(pathlib.Path(args.path).read_text())
    if not isinstance(checks, dict) or not isinstance(checks.get("checks"), dict):
        raise ValueError("expected JSON object with checks dictionary")
    required = ["source_verified", "build_verified", "tests_verified", "signature_verified",
                "backup_verified", "device_verified", "rollback_verified"]
    absent = [k for k in required if checks["checks"].get(k) is not True]
    emit({"status": "PASS" if not absent else "NO-GO", "missing_or_unverified": absent}, args.out)
    if absent:
        sys.exit(1)

def cmd_checkpoint(args):
    emit({"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "project": args.project, "baseline_sha256": args.baseline,
          "observed": args.observed, "change": args.change, "next_check": args.next,
          "status": "UNVERIFIED"}, args.out)


ROUTE_RULES = [
    {
        "id": "ios_abi_v2_apple_ci",
        "label": "R32 Apple/Xcode ABI-v2 acceptance",
        "signals": [
            (r"fptrauth[-_ ]abi[-_ ]version.{0,12}2|abi[-_ ]v2|abi_v2|abi\s+v2", "explicit ABI-v2 acceptance gate"),
            (r"apple ci|xcode|workflow_dispatch|github actions|private repository|私有仓库|苹果构建|apple workflow", "Apple/Xcode CI workflow"),
            (r"\br32\b|project.*abi|historical-build|source zip sha256", "R32 source provenance and historical CI"),
        ],
        "specialists": ["ABI/PAC-review", "ios-build-packaging", "ci-release-audit"],
        "references": ["references/ios-release-factory.md", "references/ios-reverse-auditor.md"],
        "tools": ["minis-abi preflight", "minis-abi apple-check", "existing private Apple/Xcode workflow and original verifier"],
        "gates": ["source-zip-sha256", "candidate-deb-sha256", "private-repository-access", "workflow-and-verifier-inspection", "clean-Apple-Xcode-build", "original-ABI-v2-verifier-output"],
    },
    {
        "id": "ios_reverse_engineering",
        "label": "iOS binary / reverse engineering",
        "signals": [
            (r"逆向|反汇编|mach[- ]?o|macho|dyld|disassembl|symbol table|符号表|hook|dylib|二进制|binary|swift metadata|vtable|调用链|函数地址", "binary, symbols, Hook or call-chain evidence"),
            (r"\barm64e\b|\bpac\b|\babi\b|\bobjc runtime\b|pointer authentication|指针认证", "arm64e/PAC/ABI constraints"),
        ],
        "specialists": ["binary-analysis", "ABI/PAC-review"],
        "references": ["references/ios-reverse-auditor.md", "references/ios-secure-research.md"],
        "tools": ["minis-bin <IPA|DEB|Mach-O>", "devctl.py inspect <file>"],
        "gates": ["architecture-slices", "symbol-and-callsite-evidence", "ABI/PAC-review", "no-invented-addresses"],
    },
    {
        "id": "ios_build",
        "label": "iOS / jailbreak build and packaging",
        "signals": [
            (r"\btheos\b|roothide|ellekit|rootless|越狱|tweak|\.deb\b|\bipa\b|xcodebuild|codesign|签名|安装包|编译|打包|构建|sdk|部署目标", "iOS build, packaging or signing"),
            (r"\barm64e\b|iphoneos|iphoneos sdk|架构兼容|双架构", "device architecture and SDK compatibility"),
        ],
        "specialists": ["ios-build-packaging", "dependency-and-signing-review"],
        "references": ["references/ios-release-factory.md", "references/ios-regression-lab.md"],
        "tools": ["minis-dev-ultra doctor", "minis-deb auto --project <path> --arch auto", "minis-deb doctor", "existing project build workflow", "devctl.py manifest <build-output> --out SHA256SUMS.txt"],
        "gates": ["sdk-and-architecture", "dependency-audit", "entitlements-and-install-paths", "artifact-hash", "rollback"],
    },
    {
        "id": "swift_ui",
        "label": "Swift / UIKit / SwiftUI runtime",
        "signals": [
            (r"\bswift\b|swiftui|uikit|springboard|分屏|键盘|横屏|竖屏|触摸|手势|uigesture|uiview|view controller|scene lifecycle", "Swift/UIKit/SwiftUI lifecycle or UI"),
            (r"横屏|landscape|portrait|orientation|旋转|first responder|keyboard|键盘", "keyboard/orientation/focus behavior"),
        ],
        "specialists": ["swift-ui-runtime", "lifecycle-and-ownership-review"],
        "references": ["references/ios-swiftui-runtime.md", "references/ios-input-event-router.md", "references/ios-keyboard-engine.md"],
        "tools": ["devctl.py triage <log>", "Xcode/Swift diagnostics when available"],
        "gates": ["main-thread-and-lifecycle", "gesture-and-ownership", "orientation-regression", "device-validation"],
    },
    {
        "id": "python_runtime",
        "label": "Python runtime / CLI / automation",
        "signals": [
            (r"\bpython3?\b|pip|venv|runtime|依赖安装|脚本|命令行|cli\b|自动化|工具链|执行环境", "Python runtime, dependencies or CLI"),
        ],
        "specialists": ["python-runtime", "cli-and-test-design"],
        "references": ["references/agent-tool-engineer.md", "references/devops-observability.md"],
        "tools": ["minis-dev-ultra doctor", "python3 -m py_compile", "python3 -m unittest"],
        "gates": ["runtime-bootstrap", "stdlib-or-pinned-dependencies", "py_compile", "unit-tests"],
    },
    {
        "id": "on_device_ide",
        "label": "On-device IDE / code workspace",
        "signals": [
            (r"\bapelin\b|\bon[- ]device ide\b|device-side ide|设备端 ide|本地 ide", "on-device IDE capability"),
            (r"code editor|multi-file edit|workspace editor|代码编辑器|多文件编辑|工程工作区", "project editing workspace"),
            (r"agent.*(write|build|install|debug)|智能代理.*(编写|编译|安装|调试)", "agent-driven development loop"),
        ],
        "specialists": ["agent-tool-engineer", "fullstack-implementation", "qa-test-generator"],
        "references": ["references/agent-tool-engineer.md", "references/fullstack-implementation.md", "references/qa-test-generator.md"],
        "tools": ["minis-dev-ultra doctor", "minis-dev-ultra new --kind tweak|app|cli|preferences ...", "minis-deb auto --project <path> --arch auto", "git status --short"],
        "gates": ["workspace-boundary", "minimal-diff", "compile-and-tests", "artifact-provenance", "rollback"],
    },
    {
        "id": "toolchain_sdk",
        "label": "Compiler toolchain / iPhoneOS SDK manager",
        "signals": [
            (r"\btoolchain\b|sdk manager|iphoneos sdk|apple command line tools|工具链|sdk 管理|自动配置编译器|sdk 导入", "toolchain or SDK lifecycle"),
            (r"cpu feature|instruction set|compiler.*sdk compatibility|host compiler compatibility|兼容矩阵|编译器兼容", "host CPU and compiler/SDK compatibility"),
        ],
        "specialists": ["ios-build-packaging", "dependency-and-signing-review", "python-runtime"],
        "references": ["references/ios-release-factory.md", "references/secure-code-review.md", "references/devops-observability.md"],
        "tools": ["minis-dev-ultra doctor", "minis-deb doctor", "minis-abi preflight", "verify toolchain and SDK hashes before registration"],
        "gates": ["cpu-feature-check", "compiler-sdk-compatibility", "sdk-integrity-hash", "no-silent-apple-sdk-license-acceptance"],
    },
    {
        "id": "terminal_sessions",
        "label": "Terminal / resumable development tasks",
        "signals": [
            (r"persistent terminal|terminal session|pty session|daemon-backed terminal|持久终端|终端会话|后台开发任务", "terminal session or long-running job"),
            (r"survive.*(kill|relaunch|respring)|app.*(suspend|terminate)|resume.*task|应用退出.*继续|重启后恢复|任务续跑", "session persistence or resume requirement"),
        ],
        "specialists": ["agent-tool-engineer", "devops-observability", "ios-context-keeper"],
        "references": ["references/agent-tool-engineer.md", "references/devops-observability.md", "references/ios-context-keeper.md"],
        "tools": ["current Minis/iSH terminal", "minis-dev-ultra checkpoint --project <path> --baseline <sha256>", "preserve task logs and process status"],
        "gates": ["session-survival-tested", "resume-from-checkpoint", "explicit-cancellation", "durable-task-log", "do-not-claim-daemon-unless-installed"],
    },
    {
        "id": "install_diagnostics",
        "label": "Install / respring / runtime diagnostics",
        "signals": [
            (r"install.*(tweak|deb|package)|安装.*(插件|deb|软件包)|respring|load check|loaded marker|确认.*加载|crash symbolication|symbolicate|符号化|ui tree|view hierarchy|崩溃日志|diagnostic daemon", "installation or runtime diagnosis"),
            (r"crash report|crash log|live log|截图诊断|ui action|springboard log|post-respring|重载后验证", "post-install evidence or live diagnostics"),
        ],
        "specialists": ["crash-triage", "test-and-release-audit", "security-boundary-review"],
        "references": ["references/ios-regression-lab.md", "references/ios-reverse-auditor.md", "references/secure-code-review.md"],
        "tools": ["minis-deb verify <package.deb>", "minis-dev-ultra triage <log>", "minis-bin <IPA|DEB|Mach-O>", "inspect available device log sources"],
        "gates": ["backup-before-install", "explicit-install-approval", "post-respring-load-check", "crash-log-and-symbol-evidence", "rollback"],
    },
    {
        "id": "agent_approval",
        "label": "Agent permissions / strict approval workflow",
        "signals": [
            (r"strict mode|approval mode|agent approval|approval gate|审批模式|执行前确认|代理审批|严格执行", "explicit agent approval policy"),
            (r"destructive|delete|wipe|overwrite|credential|token|secret|删除|清空|覆盖|凭据|密钥|卸载", "high-impact operation or secret boundary"),
        ],
        "specialists": ["security-boundary-review", "data-isolation-review", "test-and-release-audit"],
        "references": ["references/secure-code-review.md", "references/ios-secure-research.md", "references/qa-test-generator.md"],
        "tools": ["read-only inspection first", "minis-dev-ultra scan-secrets <path>", "minis-dev-ultra checkpoint --project <path> --baseline <sha256>"],
        "gates": ["plan-before-write", "approval-before-install-or-respring", "no-generic-privileged-exec", "redact-secrets-from-logs", "audit-each-mutating-step"],
    },
    {
        "id": "project_templates",
        "label": "Project templates / new tweak scaffolding",
        "signals": [
            (r"project template|tweak template|preference bundle|project scaffold|工程模板|插件模板|偏好设置包|脚手架", "template or scaffold request"),
            (r"create.*(tweak|plugin|project|app|cli|preferences)|new project|新建工程|创建.*(插件|项目|偏好)", "create a new project"),
            (r"theos.*project|makefile.*template|control file", "Theos project structure"),
        ],
        "specialists": ["ios-build-packaging", "agent-tool-engineer", "qa-test-generator"],
        "references": ["references/ios-release-factory.md", "references/agent-tool-engineer.md", "references/qa-test-generator.md"],
        "tools": ["minis-dev-ultra new --kind tweak|app|cli|preferences --name <name> --bundle-id <id> --path <new-path> --scheme roothide|rootless", "minis-deb doctor", "minis-deb auto --project <path> --arch auto"],
        "gates": ["refuse-existing-output-path", "valid-bundle-identity", "scheme-specific-architecture", "build-and-package-test", "no-auto-install"],
    },
    {
        "id": "git_transfer",
        "label": "Git / private credentials / project transfer",
        "signals": [
            (r"\bgit\b|github token|private repository|git remote|transfer.*(project|sdk|toolchain)|项目传输|sdk 传输|私有仓库", "source control or project transfer"),
            (r"credential|keychain|access token|secret storage|凭据|钥匙串|令牌存储|认证", "credential storage or authentication"),
        ],
        "specialists": ["security-boundary-review", "devops-observability", "artifact-provenance-review"],
        "references": ["references/secure-code-review.md", "references/devops-observability.md", "references/ios-release-factory.md"],
        "tools": ["git status --short", "minis-dev-ultra scan-secrets <repository>", "minis-dev-ultra manifest <transfer-file> --out SHA256SUMS.txt"],
        "gates": ["private-repository-scope", "keychain-or-approved-secret-store", "no-token-in-command-logs", "transfer-hash-verification", "license-and-provenance"],
    },
    {
        "id": "binary_tool_extensions",
        "label": "Disassembly / assembly agent tools",
        "signals": [
            (r"disassembl|disassemble|反汇编|反编译|符号表分析", "disassembly and symbol inspection"),
            (r"\bcapstone\b|\bkeystone\b|assembler tool|汇编器|指令汇编", "Capstone or Keystone toolchain"),
        ],
        "specialists": ["binary-analysis", "ABI/PAC-review", "security-boundary-review"],
        "references": ["references/ios-reverse-auditor.md", "references/ios-secure-research.md", "references/secure-code-review.md"],
        "tools": ["minis-bin <IPA|DEB|Mach-O>", "minis-dev-ultra inspect <binary>", "use Capstone/Keystone only if the matching licensed extension is actually installed"],
        "gates": ["tool-presence-verified", "architecture-and-symbol-evidence", "third-party-license-review", "no-placeholder-disassembler"],
    },
    {
        "id": "frontend",
        "label": "Frontend / web UI",
        "signals": [
            (r"\breact\b|\bvue\b|\bsvelte\b|\bcss\b|\bhtml\b|\btypescript\b|\btsx\b|前端|浏览器界面|web ui|responsive layout", "web UI framework or layout"),
        ],
        "specialists": ["frontend-ui", "accessibility-and-browser-testing"],
        "references": ["references/fullstack-implementation.md", "references/ui-ux-accessibility.md", "references/browser-automation-engineer.md"],
        "tools": ["project package scripts", "lint/test/build commands from package manifest"],
        "gates": ["component-tests", "lint", "responsive-regression", "production-build"],
    },
    {
        "id": "backend",
        "label": "Backend / API / data",
        "signals": [
            (r"\bapi\b|\bbackend\b|\bserver\b|\bdatabase\b|\bsql\b|\bredis\b|\bgrpc\b|后端|接口|数据库|服务端|schema migration", "API, service or database work"),
        ],
        "specialists": ["backend-api-data", "schema-and-compatibility-review"],
        "references": ["references/web-cloud-backend.md", "references/database-reliability.md"],
        "tools": ["repository test runner", "API/schema tests"],
        "gates": ["contract-tests", "migration-safety", "authz-and-input-validation", "observability"],
    },
    {
        "id": "crash_debug",
        "label": "Crash / hang / ownership triage",
        "signals": [
            (r"崩溃|闪退|黑屏|卡死|冻结|\bcrash\b|\bsigtrap\b|\bsigsegv\b|exc_bad_access|traceback|stack trace|\buaf\b|use.after.free|ownership|引用计数|内存泄漏|deadlock", "crash, hang or ownership symptoms"),
        ],
        "specialists": ["crash-triage", "ownership-and-lifecycle-review"],
        "references": ["references/ios-reverse-auditor.md", "references/ios-context-keeper.md", "references/ios-regression-lab.md"],
        "tools": ["devctl.py triage <full-log>", "preserve original log and SHA-256"],
        "gates": ["earliest-causal-error", "reproduction", "negative-controls", "no-causality-from-keyword-match-alone"],
    },
    {
        "id": "performance",
        "label": "Performance / memory / token efficiency",
        "signals": [
            (r"性能|卡顿|延迟|耗时|优化|\btoken\b|latency|throughput|memory pressure|\bcpu\b|\bmemory\b|benchmark|profil", "performance, memory, latency or token cost"),
        ],
        "specialists": ["performance-profiler", "measurement-and-regression-review"],
        "references": ["references/performance-profiler.md", "references/agent-tool-engineer.md"],
        "tools": ["baseline/candidate benchmark", "minis-tk audit <log> when token/log volume matters"],
        "gates": ["baseline-measurement", "repeatable-benchmark", "memory-and-latency-regression", "accuracy-not-traded-for-token-savings"],
    },
    {
        "id": "security",
        "label": "Security / credentials / isolation",
        "signals": [
            (r"安全|凭据|密钥|keychain|sandbox|权限|secret|credential|oauth|entitlement|隔离|隐私|authentication|authorization|app group", "credentials, identity, permissions or isolation"),
        ],
        "specialists": ["security-boundary-review", "data-isolation-review"],
        "references": ["references/secure-code-review.md", "references/ios-secure-research.md"],
        "tools": ["devctl.py scan-secrets <repo>", "inspect entitlements and identity namespaces"],
        "gates": ["secret-scan", "identity-and-entitlement-review", "data-boundary", "backup-and-rollback"],
    },
    {
        "id": "release_test",
        "label": "Testing / CI / release verification",
        "signals": [
            (r"测试|回归|\bci\b|github actions|workflow|release|artifact|交付|验收|校验|sha256|build evidence|安装测试", "tests, CI or release evidence"),
        ],
        "specialists": ["test-and-release-audit", "artifact-provenance-review"],
        "references": ["references/qa-test-generator.md", "references/ios-release-factory.md", "references/devops-observability.md"],
        "tools": ["existing CI workflow", "devctl.py manifest/verify-manifest", "signature and artifact checks"],
        "gates": ["source-provenance", "test-results", "build-result", "signature-verification", "artifact-sha256", "device-test-status"],
    },
]
GENERAL_PROFILE = {
    "id": "general_engineering",
    "label": "General engineering",
    "specialists": ["general-engineering", "test-and-release-audit"],
    "references": ["references/dev-chief-architect.md", "references/qa-test-generator.md"],
    "tools": ["minis-dev-ultra doctor", "git status --short", "git diff --check"],
    "gates": ["baseline", "minimal-diff", "tests", "evidence", "rollback"],
}

def cmd_route(args):
    task = str(args.task or "").strip()
    paths = list(args.path or [])
    combined = (task + "\n" + "\n".join(paths)).lower()
    scored = []
    for rule in ROUTE_RULES:
        hits = [label for pattern, label in rule["signals"] if re.search(pattern, combined, re.I)]
        score = len(hits)
        suffixes = [pathlib.Path(path).suffix.lower() for path in paths]
        if rule["id"] == "ios_reverse_engineering" and any(x in suffixes for x in (".ipa", ".deb", ".dylib", ".bin")):
            score += 2
            hits.append("binary artifact path supplied")
        if rule["id"] == "python_runtime" and any(x == ".py" for x in suffixes):
            score += 1
            hits.append("Python source path supplied")
        if rule["id"] == "swift_ui" and any(x in suffixes for x in (".swift", ".m", ".mm", ".h")):
            score += 1
            hits.append("Apple-platform source path supplied")
        if score:
            scored.append({"id": rule["id"], "label": rule["label"], "score": score,
                           "matched_signals": hits, "specialists": rule["specialists"],
                           "references": rule["references"], "tools": rule["tools"], "gates": rule["gates"]})
    scored.sort(key=lambda item: -item["score"])
    if not scored:
        selected = [{
            "id": GENERAL_PROFILE["id"], "label": GENERAL_PROFILE["label"], "score": 0,
            "matched_signals": ["no specialist-specific signal; use general engineering workflow"],
            "specialists": GENERAL_PROFILE["specialists"], "references": GENERAL_PROFILE["references"],
            "tools": GENERAL_PROFILE["tools"], "gates": GENERAL_PROFILE["gates"],
        }]
    else:
        threshold = max(1, scored[0]["score"] - 1)
        selected = [item for item in scored if item["score"] >= threshold][:4]
    primary = selected[0]
    specialists = []
    references = []
    tools = ["minis-dev-ultra doctor", "git status --short", "git diff --check"]
    gates = ["baseline-hash", "minimal-diff", "tests", "evidence-backed-status", "rollback-plan"]
    for item in selected:
        for specialist in item["specialists"]:
            if specialist not in specialists:
                specialists.append(specialist)
        for reference in item["references"]:
            if reference not in references:
                references.append(reference)
        for tool in item["tools"]:
            if tool not in tools:
                tools.append(tool)
        for gate in item["gates"]:
            if gate not in gates:
                gates.append(gate)
    if re.search(r"\bhook\b|hooklab|logos|MSHookMessageEx|%hook", combined, re.I):
        hook_tool = "minis-dev-ultra hook --name HookName --bundle-id com.example.hook --process com.target.app --class-name VerifiedClass --method '- (BOOL)isEnabled' --path NEW_PATH --scheme roothide"
        if hook_tool not in tools:
            tools.append(hook_tool)
    risk_text = combined
    if re.search(r"delete|wipe|reset|production|keychain|credential|oauth|entitlement|sandbox|signing|root|roothide|hook|system-wide|覆盖|删除|清理|重置|凭据|登录|权限|生产|签名|卸载|越狱|系统级", risk_text, re.I):
        risk = "high"
    elif re.search(r"modify|patch|build|install|compile|change|fix|修复|修改|编译|构建|安装|优化|开发|交付", risk_text, re.I):
        risk = "medium"
    else:
        risk = "low"
    max_score = selected[0]["score"]
    confidence = "high" if max_score >= 3 else ("medium" if max_score == 2 else "low")
    result = {
        "router_version": "1.1",
        "selection_mode": "deterministic requirement and file-path matching",
        "primary_profile": primary["id"],
        "selected_profiles": [{"id": x["id"], "score": x["score"], "matched_signals": x["matched_signals"]} for x in selected],
        "selected_specialists": specialists,
        "selected_references": references,
        "recommended_tools": tools,
        "required_gates": gates,
        "risk_level": risk,
        "confidence": confidence,
        "task_summary": task[:500],
        "next_steps": [
            "inspect the current branch, source files and existing tests before changing anything",
            "reproduce the problem or record a baseline",
            "apply the smallest evidence-backed patch",
            "run the selected profile gates and relevant regression tests",
            "verify build/artifact/signature only where applicable; record any untested device behavior",
            "keep a rollback path and report exact evidence",
        ],
        "limitations": [
            "Selects workflow profiles, specialist references and tools; it does not switch the underlying AI model or bypass provider quotas.",
            "High-risk or destructive changes still require backup, rollback and any required user confirmation.",
            "Keyword routing is a starting plan; source evidence may refine the route, but unsupported assumptions must not be presented as facts.",
        ],
    }
    emit(result, args.out)


def cmd_new(args):
    name, bundle_id = str(args.name or "").strip(), str(args.bundle_id or "").strip()
    kind, scheme = str(args.kind or ""), str(args.scheme or "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name):
        raise ValueError("NO-GO: invalid project name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*){2,}", bundle_id):
        raise ValueError("NO-GO: invalid bundle id")
    if kind not in ("tweak", "cli", "preferences", "app") or scheme not in ("roothide", "rootless"):
        raise ValueError("NO-GO: choose tweak|cli|preferences and roothide|rootless")
    raw = pathlib.Path(args.path).expanduser()
    if raw.name in ("", ".", ".."):
        raise ValueError("NO-GO: output path must name a new directory")
    target = raw.resolve()
    if target in (pathlib.Path("/"), pathlib.Path.home().resolve()):
        raise ValueError("NO-GO: refusing to scaffold over a filesystem root or home directory")
    if target.exists():
        raise FileExistsError("NO-GO: refusing to overwrite existing project path: " + str(target))
    if not target.parent.is_dir():
        raise FileNotFoundError("NO-GO: parent directory must already exist: " + str(target.parent))

    arch = "arm64e" if scheme == "roothide" else "arm64"
    package_arch = "iphoneos-arm64e" if scheme == "roothide" else "iphoneos-arm64"
    common_make = (
        "THEOS ?= $(HOME)/theos\nARCHS = " + arch + "\n"
        "TARGET = iphone:clang:latest:16.0\n"
        "THEOS_PACKAGE_SCHEME = " + scheme + "\n"
        "include $(THEOS)/makefiles/common.mk\n"
    )
    common_control = (
        "Package: " + bundle_id + "\nName: " + name + "\nVersion: 0.1.0\n"
        "Architecture: " + package_arch + "\n"
        "Maintainer: Local Developer\nAuthor: Local Developer\n"
    )
    files = {}
    if kind == "tweak":
        files = {
            "Makefile": common_make + "TWEAK_NAME = " + name + "\n" + name + "_FILES = Tweak.xm\n" + name + "_FRAMEWORKS = UIKit\ninclude $(THEOS_MAKE_PATH)/tweak.mk\n",
            "control": common_control + "Description: Starter tweak generated by Minis Dev Ultra MAX.\nSection: Tweaks\nDepends: firmware (>= 16.0), mobilesubstrate\n",
            "Tweak.xm": "#import <UIKit/UIKit.h>\n\n// Starter only: no methods are hooked.\n%ctor {\n    NSLog(@\"[Minis Dev Ultra] starter tweak loaded; no hooks installed\");\n}\n",
            name + ".plist": 'Filter = {\n    Bundles = (\n        "com.apple.springboard"\n    );\n};\n',
        }
        section = "Tweaks"
    elif kind == "cli":
        files = {
            "Makefile": common_make + "TOOL_NAME = " + name + "\n" + name + "_FILES = main.c\n" + name + "_INSTALL_PATH = /usr/local/bin\ninclude $(THEOS_MAKE_PATH)/tool.mk\n",
            "control": common_control + "Description: CLI tool generated by Minis Dev Ultra MAX.\nSection: Utilities\nDepends: firmware (>= 16.0)\n",
            "main.c": '#include <stdio.h>\n\nint main(void) {\n    puts("' + name + ' scaffold ready");\n    return 0;\n}\n',
        }
        section = "Utilities"
    elif kind == "preferences":
        bundle_name = name if name.lower().endswith("prefs") else name + "Prefs"
        files = {
            "Makefile": common_make + "BUNDLE_NAME = " + bundle_name + "\n" + bundle_name + "_BUNDLE_ID = " + bundle_id + ".prefs\n" + bundle_name + "_FILES = RootListController.m\n" + bundle_name + "_FRAMEWORKS = UIKit\n" + bundle_name + "_PRIVATE_FRAMEWORKS = Preferences\n" + bundle_name + "_INSTALL_PATH = /Library/PreferenceBundles\ninclude $(THEOS_MAKE_PATH)/bundle.mk\n",
            "control": common_control + "Description: Preference bundle generated by Minis Dev Ultra MAX.\nSection: Preferences\nDepends: firmware (>= 16.0), preferenceloader\n",
            "RootListController.m": '#import <Preferences/PSListController.h>\n#import <Preferences/PSSpecifier.h>\n@interface RootListController : PSListController\n@end\n@implementation RootListController\n- (NSArray *)specifiers {\n    if (_specifiers == nil) _specifiers = [self loadSpecifiersFromPlistName:@"Root" target:self];\n    return _specifiers;\n}\n@end\n',
            "Root.plist": '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>items</key><array><dict><key>cell</key><string>PSGroupCell</string><key>label</key><string>' + name + ' Settings</string></dict></array></dict></plist>\n',
            "layout/Library/PreferenceLoader/Preferences/" + name + ".plist": '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>entry</key><dict><key>bundle</key><string>' + bundle_name + '</string><key>cell</key><string>PSLinkCell</string><key>label</key><string>' + name + '</string></dict></dict></plist>\n',
        }
        section = "Preferences"

    else:
        files = {
            "Makefile": common_make + "APPLICATION_NAME = " + name + "\n" + name + "_BUNDLE_ID = " + bundle_id + "\n" + name + "_FILES = main.m AppDelegate.m\n" + name + "_FRAMEWORKS = UIKit\n" + name + "_INSTALL_PATH = /Applications\ninclude $(THEOS_MAKE_PATH)/application.mk\n",
            "control": common_control + "Description: UIKit application generated by Minis Dev Ultra MAX.\nSection: Applications\nDepends: firmware (>= 16.0)\n",
            "main.m": '#import <UIKit/UIKit.h>\n#import "AppDelegate.h"\nint main(int argc, char *argv[]) {\n    @autoreleasepool {\n        return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));\n    }\n}\n',
            "AppDelegate.h": '#import <UIKit/UIKit.h>\n@interface AppDelegate : UIResponder <UIApplicationDelegate>\n@property (strong, nonatomic) UIWindow *window;\n@end\n',
            "AppDelegate.m": '#import "AppDelegate.h"\n@implementation AppDelegate\n- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {\n    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];\n    UIViewController *root = [UIViewController new];\n    root.view.backgroundColor = UIColor.systemBackgroundColor;\n    UILabel *label = [[UILabel alloc] initWithFrame:root.view.bounds];\n    label.text = @"Minis Dev Ultra scaffold";\n    label.textAlignment = NSTextAlignmentCenter;\n    label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;\n    [root.view addSubview:label];\n    self.window.rootViewController = root;\n    [self.window makeKeyAndVisible];\n    return YES;\n}\n@end\n',
        }
        section = "Applications"

    files["README.md"] = (
        "# " + name + "\n\nGenerated by Minis Dev Ultra MAX as a " + kind + " project.\n"
        "Bundle ID: " + bundle_id + "\nScheme: " + scheme + "\nArchitecture: " + arch + "\n\n"
        "Run minis-deb doctor, review the generated files, then run minis-deb auto --project "
        + str(target) + " --arch auto. Inspect the report and SHA-256 before installation. "
        "This scaffold never installs packages automatically.\n"
    )
    files[".minis-dev-project.json"] = json.dumps({
        "schema_version": 1, "kind": kind, "name": name, "bundle_id": bundle_id,
        "scheme": scheme, "architecture": arch, "package_architecture": package_arch,
        "section": section, "generated_by": "Minis Dev Ultra MAX",
    }, indent=2, sort_keys=True) + "\n"

    with tempfile.TemporaryDirectory(prefix=".minis-dev-new-", dir=str(target.parent)) as temporary:
        stage = pathlib.Path(temporary) / "project"
        stage.mkdir()
        for relative, content in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        os.replace(str(stage), str(target))
    emit({
        "status": "CREATED", "path": str(target), "kind": kind, "name": name,
        "bundle_id": bundle_id, "scheme": scheme, "architecture": arch,
        "files": sorted(files),
        "next_steps": ["Review generated files.", "Run minis-deb doctor.",
                       "Run minis-deb auto --project " + str(target) + " --arch auto.",
                       "Verify package and rollback before any installation."],
        "limitations": ["Scaffolding does not prove the local toolchain can compile.",
                        "No package is installed and no privileged daemon is added."],
    }, getattr(args, "out", None))



def cmd_hook(args):
    """Create an evidence-first, pass-through Logos hook project at a new path."""
    name = str(args.name or "").strip()
    package_id = str(args.bundle_id or "").strip()
    process_id = str(args.process or "").strip()
    class_name = str(args.class_name or "").strip()
    method_decl = str(args.method or "").strip()
    scheme = str(args.scheme or "").strip()

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name):
        raise ValueError("NO-GO: invalid project name")
    bundle_pattern = r"[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*){2,}"
    if not re.fullmatch(bundle_pattern, package_id):
        raise ValueError("NO-GO: invalid package bundle id")
    if not re.fullmatch(bundle_pattern, process_id):
        raise ValueError("NO-GO: invalid target process bundle id")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", class_name):
        raise ValueError("NO-GO: class name must be a verified Objective-C runtime identifier")
    if scheme not in ("roothide", "rootless"):
        raise ValueError("NO-GO: choose roothide|rootless")

    # Accept a single-line Objective-C method declaration only. C functions,
    # variadics, blocks and unknown prototypes require separate ABI evidence.
    signature = re.fullmatch(
        r"(?P<sign>[+-])\s*\((?P<return>[^()\r\n;{}#]+)\)\s*"
        r"(?P<selector>[A-Za-z_][A-Za-z0-9_]*"
        r"(?::\s*\([^()\r\n;{}#]+\)\s*[A-Za-z_][A-Za-z0-9_]*"
        r"(?:\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*\([^()\r\n;{}#]+\)\s*[A-Za-z_][A-Za-z0-9_]*)*)?)",
        method_decl,
    )
    if not signature:
        raise ValueError("NO-GO: supply one exact verified Objective-C method declaration, e.g. '- (BOOL)isEnabled' or '- (void)setEnabled:(BOOL)enabled'; C function hooks are not scaffolded")
    return_type = signature.group("return").strip()
    if not return_type or len(method_decl) > 240:
        raise ValueError("NO-GO: invalid or overlong Objective-C method declaration")

    raw = pathlib.Path(args.path).expanduser()
    if raw.name in ("", ".", ".."):
        raise ValueError("NO-GO: output path must name a new directory")
    target = raw.resolve()
    if target in (pathlib.Path("/"), pathlib.Path.home().resolve()):
        raise ValueError("NO-GO: refusing to scaffold over a filesystem root or home directory")
    if target.exists():
        raise FileExistsError("NO-GO: refusing to overwrite existing project path: " + str(target))
    if not target.parent.is_dir():
        raise FileNotFoundError("NO-GO: parent directory must already exist: " + str(target.parent))

    arch = "arm64e" if scheme == "roothide" else "arm64"
    package_arch = "iphoneos-arm64e" if scheme == "roothide" else "iphoneos-arm64"
    common_make = (
        "THEOS ?= $(HOME)/theos\nARCHS = " + arch + "\n"
        "TARGET = iphone:clang:latest:16.0\n"
        "THEOS_PACKAGE_SCHEME = " + scheme + "\n"
        "include $(THEOS)/makefiles/common.mk\n"
    )
    common_control = (
        "Package: " + package_id + "\nName: " + name + "\nVersion: 0.1.0\n"
        "Architecture: " + package_arch + "\n"
        "Maintainer: Local Developer\nAuthor: Local Developer\n"
    )
    call_original = "%orig;" if return_type == "void" else "return %orig;"
    source = (
        "#import <Foundation/Foundation.h>\n#import <UIKit/UIKit.h>\n\n"
        "// Generated by HookLab as a pass-through scaffold.\n"
        "// Verify class/selector/signature in static and runtime evidence before use.\n"
        "%hook " + class_name + "\n"
        + method_decl + " {\n"
        "    " + call_original + "\n"
        "}\n"
        "%end\n\n"
        "%ctor {\n"
        "    @autoreleasepool {\n"
        "        NSLog(@\"[MinisDevUltraHookLab] loaded " + name
        + "; target process=" + process_id + "; pass-through only\");\n"
        "    }\n"
        "}\n"
    )
    files = {
        "Makefile": common_make + "TWEAK_NAME = " + name + "\n"
            + name + "_FILES = Tweak.xm\n" + name
            + "_FRAMEWORKS = Foundation UIKit\ninclude $(THEOS_MAKE_PATH)/tweak.mk\n",
        "control": common_control + "Description: Evidence-first pass-through hook scaffold generated by Minis Dev Ultra MAX.\nSection: Tweaks\nDepends: firmware (>= 16.0), mobilesubstrate\n",
        "Tweak.xm": source,
        name + ".plist": 'Filter = {\n    Bundles = (\n        "' + process_id + '"\n    );\n};\n',
        "README.md": (
            "# " + name + " — HookLab scaffold\n\n"
            "Target process: " + process_id + "\n\n"
            "Objective-C class: " + class_name + "\n\n"
            "Method declaration: " + method_decl + "\n\n"
            "The generated hook is pass-through only (%orig) and is not proof the target exists. "
            "Confirm the bundle, class, selector, return type, arguments, caller context and iOS version "
            "from actual binary/runtime evidence. This generator does not scaffold C function hooks because "
            "their exact prototype and ABI must be independently proven. No package is installed automatically.\n\n"
            "Next: run minis-deb doctor, review all generated files, run the relevant tests, then "
            "minis-deb auto --project " + str(target) + " --arch auto. Verify DEB metadata, slices, "
            "signature structure and SHA-256; runtime behavior still needs device testing.\n"
        ),
        ".minis-dev-project.json": json.dumps({
            "schema_version": 1, "kind": "hook", "name": name,
            "bundle_id": package_id, "target_process_bundle_id": process_id,
            "class_name": class_name, "method_declaration": method_decl,
            "scheme": scheme, "architecture": arch, "package_architecture": package_arch,
            "generated_by": "Minis Dev Ultra MAX HookLab",
            "status": "PASS_THROUGH_TEMPLATE_REQUIRES_EVIDENCE_AND_DEVICE_VALIDATION",
        }, indent=2, sort_keys=True) + "\n",
    }
    with tempfile.TemporaryDirectory(prefix=".minis-dev-hook-", dir=str(target.parent)) as temporary:
        stage = pathlib.Path(temporary) / "project"
        stage.mkdir()
        for relative, content in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        os.replace(str(stage), str(target))
    emit({
        "status": "CREATED_TEMPLATE_NOT_RUNTIME_VERIFIED",
        "path": str(target), "kind": "hook", "name": name,
        "package_bundle_id": package_id, "target_process_bundle_id": process_id,
        "class_name": class_name, "method_declaration": method_decl,
        "scheme": scheme, "architecture": arch, "files": sorted(files),
        "next_steps": [
            "Verify target process, class, selector and full method signature from real evidence.",
            "Review the pass-through implementation and generated filter before compiling.",
            "Run minis-deb doctor, then build and verify the DEB without auto-installing it.",
            "Test only on a backed-up test device and record load/crash evidence.",
        ],
        "limitations": [
            "This creates a starter, not proof that the target method exists or that the hook is compatible.",
            "C function hooks, guessed offsets and unverified ABIs are intentionally not generated.",
            "No package is installed and no source/target binary is modified.",
        ],
    }, getattr(args, "out", None))



def main(argv=None):
    p = argparse.ArgumentParser(description="Minis Dev Ultra MAX reproducible offline developer tools")
    sp = p.add_subparsers(dest="command", required=True)
    def add(name, handler, *paths):
        q = sp.add_parser(name)
        for field in paths:
            q.add_argument(field)
        if name != "manifest":
            q.add_argument("--out")
        q.set_defaults(func=handler)
        return q
    add("doctor", cmd_doctor)
    add("inspect", cmd_inspect, "path")
    q = add("triage", cmd_triage, "path")
    q.add_argument("--limit", type=int, default=15)
    add("scan-secrets", cmd_secrets, "path")
    add("diffzip", cmd_diff, "old", "new")
    q = sp.add_parser("manifest"); q.add_argument("path"); q.add_argument("--out", required=True); q.set_defaults(func=cmd_manifest)
    q = add("verify-manifest", cmd_verify, "path"); q.add_argument("--root", required=True)
    add("gate", cmd_gate, "path")
    q = add("checkpoint", cmd_checkpoint)
    q.add_argument("--project", required=True); q.add_argument("--baseline", required=True)
    q.add_argument("--observed", default=""); q.add_argument("--change", default="")
    q.add_argument("--next", default="")
    q = add("route", cmd_route)
    q.add_argument("--task", required=True, help="Development requirement in natural language")
    q.add_argument("--path", action="append", default=[], help="Optional project file path; may be repeated")
    q = sp.add_parser("new", help="Safely scaffold a new Theos tweak, CLI or preference bundle")
    q.add_argument("--kind", choices=("tweak", "app", "cli", "preferences"), required=True)
    q.add_argument("--name", required=True)
    q.add_argument("--bundle-id", required=True)
    q.add_argument("--path", required=True, help="New output directory; existing paths are never overwritten")
    q.add_argument("--scheme", choices=("roothide", "rootless"), default="roothide")
    q.set_defaults(func=cmd_new)
    q = sp.add_parser("hook", help="Create a pass-through Logos hook scaffold from verified Objective-C evidence")
    q.add_argument("--name", required=True)
    q.add_argument("--bundle-id", required=True, help="New tweak package bundle id")
    q.add_argument("--process", required=True, help="Verified target process bundle id")
    q.add_argument("--class-name", required=True, help="Verified Objective-C runtime class")
    q.add_argument("--method", required=True, help="Exact one-line Objective-C declaration, e.g. '- (BOOL)isEnabled'")
    q.add_argument("--path", required=True, help="New output directory; existing paths are never overwritten")
    q.add_argument("--scheme", choices=("roothide", "rootless"), default="roothide")
    q.set_defaults(func=cmd_hook)
    args = p.parse_args(argv)
    try:
        args.func(args)
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        print("NO-GO:", e, file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
