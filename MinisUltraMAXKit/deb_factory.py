#!/usr/bin/env python3
"""Local-first Theos DEB build factory with automatic environment preparation.
Uses existing SDKs/toolchains, installs host packages when supported, and verifies artifacts.
It never silently downloads Apple SDKs or installs the resulting package.
"""
import argparse, hashlib, json, os, pathlib, platform, re, shutil, struct, subprocess, sys, tempfile, time

IGNORED_DIRS = {".git", ".theos", "node_modules", "vendor", "Pods", "DerivedData", "__pycache__"}
MACHO_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"}
LC_CODE_SIGNATURE = 0x1d


def run(argv, cwd=None, env=None, timeout=120, check=False):
    try:
        p = subprocess.run([str(x) for x in argv], cwd=str(cwd) if cwd else None, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace", timeout=timeout)
        result = {"argv": [str(x) for x in argv], "returncode": p.returncode, "output": p.stdout}
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = {"argv": [str(x) for x in argv], "returncode": 127, "output": str(exc)}
    if check and result["returncode"] != 0:
        raise RuntimeError("{} failed ({}): {}".format(" ".join(result["argv"]), result["returncode"], result["output"][-4000:]))
    return result


def is_executable(path):
    return bool(path and pathlib.Path(path).is_file() and os.access(str(path), os.X_OK))


def find_theos(explicit=None):
    home = pathlib.Path.home()
    candidates = [pathlib.Path(explicit).expanduser()] if explicit else []
    if os.environ.get("THEOS"):
        candidates.append(pathlib.Path(os.environ["THEOS"]).expanduser())
    candidates.extend([home / ".cache/minis-dev-ultra/theos", home / "theos", home / ".theos",
                       pathlib.Path("/var/mobile/theos"), pathlib.Path("/var/jb/var/mobile/theos"),
                       pathlib.Path("/opt/theos"), pathlib.Path("/usr/local/theos")])
    seen = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if str(candidate) in seen:
            continue
        seen.add(str(candidate))
        if (candidate / "makefiles/common.mk").is_file():
            return candidate
    return None


def version_key(value):
    nums = re.findall(r"\d+", value)
    return tuple(int(x) for x in nums) if nums else (0,)


def find_make():
    for name in ("gmake", "make"):
        path = shutil.which(name)
        if path:
            probe = run([path, "--version"], timeout=5)
            if probe["returncode"] == 0 and "GNU Make" in probe["output"]:
                return path
    return None


def find_tool(name, theos=None):
    path = shutil.which(name)
    if path:
        return path
    if theos:
        for candidate in [theos / "bin" / name, theos / "toolchain/linux/iphone/bin" / name,
                          theos / "toolchain/darwin/iphone/bin" / name]:
            if is_executable(candidate):
                return str(candidate)
        if name in ("clang", "clang++"):
            for candidate in theos.glob("toolchain/**/bin/" + name):
                if is_executable(candidate):
                    return str(candidate)
    return None


def sdk_version(path):
    if not path:
        return None
    match = re.search(r"iPhoneOS([0-9]+(?:\.[0-9]+)*)\.sdk$", str(pathlib.Path(path)))
    return match.group(1) if match else None


def find_sdk(theos=None):
    raw = os.environ.get("SDKROOT")
    if raw:
        p = pathlib.Path(raw).expanduser()
        if p.is_dir() and (p.name.startswith("iPhoneOS") or "iPhoneOS.platform" in str(p)):
            ver = sdk_version(p)
            xcrun = shutil.which("xcrun")
            if not ver and xcrun:
                probe = run([xcrun, "--sdk", "iphoneos", "--show-sdk-version"], timeout=10)
                ver = probe["output"].strip() if probe["returncode"] == 0 else None
            return p.resolve(), ver
    if theos:
        candidates = [p for p in (theos / "sdks").glob("iPhoneOS*.sdk") if p.is_dir()]
        if candidates:
            candidates.sort(key=lambda p: version_key(p.name), reverse=True)
            return candidates[0].resolve(), sdk_version(candidates[0])
    xcrun = shutil.which("xcrun")
    if xcrun:
        result = run([xcrun, "--sdk", "iphoneos", "--show-sdk-path"], timeout=10)
        if result["returncode"] == 0:
            p = pathlib.Path(result["output"].strip())
            if p.is_dir():
                ver = run([xcrun, "--sdk", "iphoneos", "--show-sdk-version"], timeout=10)
                return p.resolve(), ver["output"].strip() if ver["returncode"] == 0 else None
    return None, None


def parse_make_variable(text, name):
    pattern = re.compile(r"^\s*(?:(?:override|export)\s+)*" + re.escape(name) + r"\s*([:+?]?=)\s*(.*?)\s*$")
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            value = match.group(2).split("#", 1)[0].strip()
            if "$" in value:
                return {"present": True, "value": None}
            return {"present": True, "value": value}
    return {"present": False, "value": None}


def parse_arch_list(value):
    return [x for x in re.split(r"[\s,]+", value.strip()) if x] if value else []


def project_shape(path):
    if not path.is_dir():
        return False
    has_make = any((path / name).is_file() for name in ("Makefile", "makefile", "GNUmakefile"))
    has_control = (path / "control").is_file() or (path / "layout/DEBIAN/control").is_file()
    return has_make and has_control


def discover_project(start):
    start = pathlib.Path(start).expanduser().resolve()
    for candidate in [start] + list(start.parents)[:6]:
        if project_shape(candidate):
            return candidate, []
    home = pathlib.Path.home()
    roots = [home / "projects", home / "workspace", home / "src", home / "Documents"]
    found, visited = [], 0
    for root in roots:
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            if len(pathlib.Path(current).relative_to(root).parts) >= 4:
                dirs[:] = []
            visited += 1
            if visited > 4000:
                break
            if project_shape(pathlib.Path(current)):
                found.append(pathlib.Path(current).resolve())
        if visited > 4000:
            break
    unique = sorted(set(found), key=lambda p: (len(p.parts), str(p)))
    if len(unique) == 1:
        return unique[0], []
    return None, [str(x) for x in unique[:20]]


def toolchain_paths(theos):
    paths = [str(theos / "bin")]
    paths.extend(str(p) for p in theos.glob("toolchain/**/bin") if p.is_dir())
    paths.extend(os.environ.get("PATH", "").split(os.pathsep))
    seen = set()
    return [p for p in paths if p and not (p in seen or seen.add(p))]


def inspect_environment():
    theos = find_theos()
    sdk, sdkver = find_sdk(theos)
    tools = {"make": find_make(), "clang": find_tool("clang", theos), "ldid": find_tool("ldid", theos),
             "dpkg-deb": shutil.which("dpkg-deb"), "perl": shutil.which("perl"),
             "bash": shutil.which("bash"), "git": shutil.which("git")}
    info = {"host": platform.system(), "machine": platform.machine(), "python": sys.version.split()[0],
            "theos": str(theos) if theos else None, "sdk": str(sdk) if sdk else None,
            "sdk_version": sdkver, "tools": tools, "missing": [], "notes": []}
    for key in ("make", "clang", "ldid", "dpkg-deb", "perl", "bash"):
        if not tools[key]:
            info["missing"].append(key)
        else:
            probe = run([tools[key], "-h" if key == "ldid" else "--version"], timeout=8)
            if probe["returncode"] == 127:
                info["missing"].append(key + " (not executable on this host)")
    if not theos:
        info["missing"].append("THEOS")
    if not sdk:
        info["missing"].append("iPhoneOS SDK")
    if info["host"] == "Darwin" and not shutil.which("xcrun"):
        info["notes"].append("xcrun unavailable; Xcode SDK auto-discovery is disabled.")
    if info["host"] == "Linux" and info["machine"].lower() in ("i386", "i486", "i586", "i686"):
        info["notes"].append("32-bit x86 host detected; compiler/linker executability must be confirmed for arm64e.")
    if not tools["ldid"]:
        info["notes"].append("Device builds require ldid or an explicitly configured compatible signing command.")
    info["ready"] = not info["missing"]
    info["status"] = "ready" if info["ready"] else "needs_setup"
    return info


def package_manager_install():
    commands = []
    if shutil.which("apk"):
        commands = [
            ["apk", "add", "--no-cache", "bash", "coreutils", "curl", "dpkg", "file", "findutils",
             "git", "make", "perl", "python3", "clang", "llvm", "lld"],
            ["apk", "add", "--no-cache", "ldid"],
        ]
    elif shutil.which("apt-get"):
        prefix = []
        if getattr(os, "geteuid", lambda: 1)() != 0:
            sudo = shutil.which("sudo")
            if not sudo or run([sudo, "-n", "true"], timeout=5)["returncode"] != 0:
                return {"ok": False, "reason": "apt-get needs root and passwordless sudo is unavailable"}
            prefix = [sudo, "-n"]
        commands = [
            prefix + ["apt-get", "update"],
            prefix + ["apt-get", "install", "-y", "bash", "build-essential", "clang", "lld", "dpkg",
                      "dpkg-dev", "file", "findutils", "git", "perl", "python3", "curl", "ca-certificates"],
            prefix + ["apt-get", "install", "-y", "ldid"],
        ]
    elif shutil.which("brew"):
        brew = shutil.which("brew")
        commands = [[brew, "install", "make", "llvm", "ldid", "dpkg", "perl", "git", "bash"]]
    else:
        return {"ok": False, "reason": "no supported package manager (apk, apt-get, or brew) is available"}
    results = []
    for argv in commands:
        result = run(argv, timeout=900)
        results.append({"command": argv, "returncode": result["returncode"], "output": result["output"][-2500:]})
        if result["returncode"] != 0 and not (argv[-1] == "ldid"):
            return {"ok": False, "reason": "dependency installation failed", "results": results}
    return {"ok": True, "results": results}


def bootstrap_environment():
    before = inspect_environment()
    actions = []
    host_tool_missing = [x for x in before["missing"] if x in ("make", "clang", "ldid", "dpkg-deb", "perl", "bash") or "not executable" in x]
    need_git_for_clone = not before["theos"] and not before["tools"].get("git")
    if host_tool_missing or need_git_for_clone:
        installed = package_manager_install()
        actions.append({"step": "host dependencies", **installed})
        if not installed["ok"]:
            return {"ok": False, "before": before, "actions": actions,
                    "reason": installed.get("reason", "host dependencies could not be installed")}
    theos = find_theos()
    if not theos:
        git = shutil.which("git")
        if not git:
            return {"ok": False, "before": before, "actions": actions, "reason": "git is unavailable"}
        destination = pathlib.Path.home() / ".cache/minis-dev-ultra/theos"
        if destination.exists():
            return {"ok": False, "before": before, "actions": actions,
                    "reason": "managed Theos destination exists but is incomplete; refusing to overwrite: " + str(destination)}
        destination.parent.mkdir(parents=True, exist_ok=True)
        clone = run([git, "clone", "--depth", "1", "--recursive", "https://github.com/theos/theos.git", str(destination)], timeout=900)
        actions.append({"step": "install Theos", "returncode": clone["returncode"], "output": clone["output"][-3000:]})
        if clone["returncode"] != 0:
            return {"ok": False, "before": before, "actions": actions, "reason": "Theos clone failed"}
        theos = destination
    sdk, sdkver = find_sdk(theos)
    if not sdk and shutil.which("xcrun"):
        result = run([shutil.which("xcrun"), "--sdk", "iphoneos", "--show-sdk-path"], timeout=10)
        if result["returncode"] == 0:
            source = pathlib.Path(result["output"].strip())
            ver = run([shutil.which("xcrun"), "--sdk", "iphoneos", "--show-sdk-version"], timeout=10)
            sdkver = ver["output"].strip() if ver["returncode"] == 0 else None
            if source.is_dir() and sdkver:
                sdkdir = theos / "sdks"
                sdkdir.mkdir(parents=True, exist_ok=True)
                target = sdkdir / ("iPhoneOS" + sdkver + ".sdk")
                if not target.exists():
                    try:
                        target.symlink_to(source, target_is_directory=True)
                        actions.append({"step": "link existing Xcode SDK", "source": str(source), "target": str(target)})
                    except OSError as exc:
                        actions.append({"step": "link existing Xcode SDK", "error": str(exc)})
    after = inspect_environment()
    ok = after["ready"]
    return {"ok": ok, "before": before, "after": after, "actions": actions,
            "reason": None if ok else "compiler, signer, GNU make, dpkg-deb, Theos or iPhoneOS SDK is still unavailable. No Apple SDK was downloaded or license agreement accepted."}


def architecture_name(cpu, subtype):
    cpu &= 0xffffffff
    subtype &= 0xffffffff
    if cpu == 0x0100000c:
        return "arm64e" if (subtype & 0xff) == 2 else "arm64"
    if cpu == 0x01000007:
        return "x86_64"
    if cpu == 12:
        return "arm"
    if cpu == 7:
        return "i386"
    if cpu == 0x01000012:
        return "arm64_32"
    return "cpu_{:08x}_subtype_{:08x}".format(cpu, subtype)


def parse_macho_slice(stream, offset, size):
    stream.seek(offset)
    header = stream.read(32)
    if len(header) < 28:
        return None
    if header[:4] == b"\xcf\xfa\xed\xfe":
        endian = "<"
    elif header[:4] == b"\xfe\xed\xfa\xcf":
        endian = ">"
    else:
        return None
    try:
        cpu, subtype = struct.unpack(endian + "ii", header[4:12])
        ncmds = struct.unpack(endian + "I", header[16:20])[0]
    except struct.error:
        return None
    signed, cursor, upper = False, offset + 32, offset + size
    if ncmds > 20000:
        ncmds = 0
    for _ in range(ncmds):
        if cursor + 8 > upper:
            break
        stream.seek(cursor)
        raw = stream.read(8)
        if len(raw) != 8:
            break
        command, command_size = struct.unpack(endian + "II", raw)
        if command_size < 8 or cursor + command_size > upper:
            break
        if command == LC_CODE_SIGNATURE and command_size >= 16:
            raw = stream.read(8)
            if len(raw) == 8:
                dataoff, datasize = struct.unpack(endian + "II", raw)
                signed = datasize > 0 and dataoff + datasize <= size
        cursor += command_size
    return {"architecture": architecture_name(cpu, subtype), "signed": signed,
            "cpu": cpu & 0xffffffff, "subtype": subtype & 0xffffffff, "offset": offset, "size": size}


def macho_slices(path):
    size = path.stat().st_size
    with path.open("rb") as stream:
        magic = stream.read(4)
        if magic in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
            item = parse_macho_slice(stream, 0, size)
            return [item] if item else []
        if magic not in MACHO_MAGICS:
            return []
        stream.seek(0)
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError("truncated universal Mach-O header: " + str(path))
        magic_value, count = struct.unpack(">II", header)
        endian = ">"
        is64 = magic_value == 0xcafebabf
        if magic_value in (0xbebafeca, 0xbfbafeca):
            magic_value, count = struct.unpack("<II", header)
            endian = "<"
            is64 = magic_value == 0xcafebabf
        if count < 1 or count > 64:
            raise ValueError("implausible universal slice count: " + str(path))
        entry_size = 32 if is64 else 20
        table = stream.read(count * entry_size)
        if len(table) != count * entry_size:
            raise ValueError("truncated universal Mach-O table: " + str(path))
        slices = []
        for index in range(count):
            entry = table[index * entry_size:(index + 1) * entry_size]
            if is64:
                cpu, subtype, offset, slice_size, align, reserved = struct.unpack(endian + "iiQQII", entry)
            else:
                cpu, subtype, offset, slice_size, align = struct.unpack(endian + "iiIII", entry)
            if offset < 8 + count * entry_size or slice_size < 32 or offset + slice_size > size:
                raise ValueError("invalid universal slice bounds: " + str(path))
            item = parse_macho_slice(stream, offset, slice_size)
            if item:
                slices.append(item)
        return slices


def file_sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_package(package, expected_archs=None, require_signature=True, out_dir=None):
    package = pathlib.Path(package).expanduser().resolve()
    if not package.is_file() or package.suffix.lower() != ".deb":
        raise RuntimeError("package path must point to an existing .deb file")
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        raise RuntimeError("dpkg-deb is required for independent package verification")
    info = run([dpkg_deb, "-f", package, "Package", "Version", "Architecture"], timeout=30)
    if info["returncode"] != 0:
        raise RuntimeError("DEB control metadata verification failed: " + info["output"][-3000:])
    fields = [line.strip() for line in info["output"].splitlines() if line.strip()]
    if len(fields) < 3:
        raise RuntimeError("DEB metadata is incomplete: " + repr(fields))
    metadata = {"package": fields[0], "version": fields[1], "package_architecture": fields[2]}
    listing = run([dpkg_deb, "--contents", package], timeout=30)
    if listing["returncode"] != 0 or not listing["output"].strip():
        raise RuntimeError("DEB file list verification failed: " + listing["output"][-2000:])
    with tempfile.TemporaryDirectory(prefix="minis-deb-verify-") as td:
        extracted = pathlib.Path(td) / "root"
        extracted.mkdir()
        unpack = run([dpkg_deb, "-x", package, extracted], timeout=120)
        if unpack["returncode"] != 0:
            raise RuntimeError("DEB extraction verification failed: " + unpack["output"][-2000:])
        binaries, errors = [], []
        for path in extracted.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                slices = macho_slices(path)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
                continue
            if not slices:
                continue
            arches = sorted(set(x["architecture"] for x in slices))
            unsigned = [x["architecture"] for x in slices if not x["signed"]]
            missing = sorted(set(expected_archs or []) - set(arches))
            binaries.append({"path": str(path.relative_to(extracted)), "architectures": arches,
                             "all_slices_signed": not unsigned, "unsigned_slices": unsigned})
            if missing:
                errors.append("{} missing required architecture(s): {}".format(path.relative_to(extracted), ", ".join(missing)))
            if require_signature and unsigned:
                errors.append("{} has Mach-O slice(s) without LC_CODE_SIGNATURE: {}".format(path.relative_to(extracted), ", ".join(unsigned)))
        if errors:
            raise RuntimeError("DEB binary verification failed: " + "; ".join(errors[:12]))
    result = {"status": "PASS", "package": str(package), **metadata, "sha256": file_sha256(package),
              "size_bytes": package.stat().st_size, "macho_files": binaries,
              "signature_check": "LC_CODE_SIGNATURE present on every Mach-O slice" if binaries and require_signature else ("no Mach-O payloads" if not binaries else "signature presence inspected")}
    if out_dir:
        output = pathlib.Path(out_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "BUILD_REPORT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "SHA256SUMS.txt").write_text("{}  {}\n".format(result["sha256"], package.name), encoding="utf-8")
    return result


def default_arches_for_project(text, sdk):
    deployment = None
    for key in ("TARGET_OS_DEPLOYMENT_VERSION", "IPHONEOS_DEPLOYMENT_TARGET"):
        value = parse_make_variable(text, key)
        if value["value"]:
            deployment = value["value"]
            break
    if not deployment:
        match = re.search(r"^\s*TARGET\s*[:?+]?=\s*iphone:clang:[^:\s]+:([0-9]+(?:\.[0-9]+)*)", text, re.M)
        if match:
            deployment = match.group(1)
    sdkver = sdk_version(sdk) or "16.0"
    if deployment and version_key(deployment) < version_key("11.0"):
        return ["arm64"]
    return ["arm64", "arm64e"] if version_key(sdkver) >= version_key("12.1") else ["arm64"]


def build_plan(project, arch_option="auto", scheme_option="auto", env=None, theos=None, sdk=None):
    env = dict(os.environ if env is None else env)
    makefile = next((project / name for name in ("Makefile", "makefile", "GNUmakefile") if (project / name).is_file()), None)
    if not makefile:
        raise RuntimeError("no Makefile, makefile or GNUmakefile found")
    text = makefile.read_text(encoding="utf-8", errors="replace")
    arch_cfg = parse_make_variable(text, "ARCHS")
    scheme_cfg = parse_make_variable(text, "THEOS_PACKAGE_SCHEME")
    sign_cfg = parse_make_variable(text, "TARGET_CODESIGN")
    sign_flags_cfg = parse_make_variable(text, "TARGET_CODESIGN_FLAGS")
    args, expected_archs = [], []
    if arch_option != "auto":
        expected_archs = parse_arch_list(arch_option)
        if not expected_archs:
            raise RuntimeError("invalid --arch value")
        args.append("ARCHS=" + " ".join(expected_archs))
        arch_source = "explicit CLI override"
    elif arch_cfg["present"]:
        expected_archs = parse_arch_list(arch_cfg["value"])
        arch_source = "project Makefile" if expected_archs else "dynamic project Makefile; preserved without override"
    else:
        expected_archs = default_arches_for_project(text, sdk)
        arch_source = "Theos default for selected SDK/deployment target; preserved without override"
    if scheme_option == "rootful":
        args.append("THEOS_PACKAGE_SCHEME=")
        scheme_source = "explicit rootful selection; package scheme cleared"
    elif scheme_option != "auto":
        args.append("THEOS_PACKAGE_SCHEME=" + scheme_option)
        scheme_source = "explicit CLI override"
    elif scheme_cfg["present"]:
        scheme_source = "project Makefile; preserved"
    elif env.get("THEOS_PACKAGE_SCHEME"):
        scheme_source = "existing environment; preserved"
    else:
        scheme_source = "Theos project default; no forced scheme"
    if sign_cfg["present"]:
        signer = sign_cfg["value"]
    elif env.get("TARGET_CODESIGN"):
        signer = env["TARGET_CODESIGN"]
    else:
        signer = "ldid"
        args.append("TARGET_CODESIGN=ldid")
    if not sign_flags_cfg["present"] and not env.get("TARGET_CODESIGN_FLAGS"):
        if signer is not None and pathlib.Path(signer).name == "ldid":
            args.append("TARGET_CODESIGN_FLAGS=-S")
        elif signer is not None:
            raise RuntimeError("custom TARGET_CODESIGN is configured without TARGET_CODESIGN_FLAGS; refusing to guess signing arguments")
        elif sign_cfg["present"]:
            raise RuntimeError("dynamic TARGET_CODESIGN is configured without TARGET_CODESIGN_FLAGS; refusing to guess signing arguments")
    signing_label = "Theos TARGET_CODESIGN pipeline; {}".format(signer or "dynamic project signer preserved")
    return {"makefile": str(makefile), "make_args": args, "expected_archs": expected_archs,
            "arch_source": arch_source, "scheme_source": scheme_source, "signing": signing_label}


def build_package(project, out_dir=None, arch_option="auto", scheme_option="auto", timeout=1800, auto_setup=True):
    project = pathlib.Path(project).expanduser().resolve()
    if not project_shape(project):
        detected, candidates = discover_project(project)
        if detected:
            project = detected
        elif candidates:
            raise RuntimeError("project path is ambiguous; candidates: " + ", ".join(candidates))
        else:
            raise RuntimeError("project must contain a Theos Makefile and control or layout/DEBIAN/control")
    if " " in str(project):
        raise RuntimeError("Theos does not support project paths containing spaces")
    env_info = inspect_environment()
    if not env_info["ready"] and auto_setup:
        setup = bootstrap_environment()
        if not setup.get("ok"):
            raise RuntimeError("automatic environment setup could not finish: " + str(setup.get("reason")) +
                               "\nSetup report: " + json.dumps(setup, sort_keys=True))
        env_info = inspect_environment()
    if not env_info["ready"]:
        raise RuntimeError("local build environment is not ready: " + json.dumps(env_info, sort_keys=True))
    theos, sdk = pathlib.Path(env_info["theos"]), pathlib.Path(env_info["sdk"])
    plan_sdk = pathlib.Path("iPhoneOS" + env_info["sdk_version"] + ".sdk") if env_info["sdk_version"] else sdk
    plan = build_plan(project, arch_option, scheme_option, theos=theos, sdk=plan_sdk)
    out = pathlib.Path(out_dir).expanduser().resolve() if out_dir else project / "packages"
    out.mkdir(parents=True, exist_ok=True)
    log_path, packages_dir = out / "minis-deb-build.log", project / "packages"
    before = {}
    if packages_dir.exists():
        for p in packages_dir.rglob("*.deb"):
            if p.is_file():
                before[str(p.resolve())] = file_sha256(p)
    env = os.environ.copy()
    env["THEOS"] = str(theos)
    env["SDKVERSION"] = env_info["sdk_version"] or env.get("SDKVERSION", "latest")
    env["TARGET_CODESIGN"] = env.get("TARGET_CODESIGN") or "ldid"
    if not env.get("TARGET_CODESIGN_FLAGS") and any(x == "TARGET_CODESIGN_FLAGS=-S" for x in plan["make_args"]):
        env["TARGET_CODESIGN_FLAGS"] = "-S"
    env["PATH"] = os.pathsep.join(toolchain_paths(theos))
    start_ns = time.time_ns()
    command = [env_info["tools"]["make"], "-C", str(project), "package", "FINALPACKAGE=1"] + plan["make_args"]
    with log_path.open("w", encoding="utf-8") as log:
        log.write("Command: " + " ".join(command) + "\nTheos: " + str(theos) + "\nSDK: " + str(sdk) + "\n")
        log.write("Signing: " + plan["signing"] + "\n\n")
        log.flush()
        try:
            proc = subprocess.run(command, cwd=str(project), env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            returncode = proc.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.write("\nNO-GO: " + str(exc) + "\n")
            returncode = 127
    if returncode != 0:
        raise RuntimeError("Theos package build failed; see " + str(log_path) + "\n" + log_path.read_text(encoding="utf-8", errors="replace")[-8000:])
    candidates = []
    if packages_dir.exists():
        for p in packages_dir.rglob("*.deb"):
            if p.is_file() and (p.stat().st_mtime_ns >= start_ns or before.get(str(p.resolve())) != file_sha256(p)):
                candidates.append(p.resolve())
    last_package = project / ".theos/last_package"
    if not candidates and last_package.is_file():
        p = pathlib.Path(last_package.read_text(encoding="utf-8", errors="replace").strip())
        if not p.is_absolute():
            p = project / p
        if p.is_file() and p.suffix == ".deb":
            candidates.append(p.resolve())
    if not candidates:
        raise RuntimeError("make package returned success but no fresh .deb artifact was found; see " + str(log_path))
    source_package = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    target_package = out / source_package.name
    if source_package != target_package:
        shutil.copy2(source_package, target_package)
    result = verify_package(target_package, expected_archs=plan["expected_archs"], require_signature=True, out_dir=out)
    result.update({"build_command": command, "project": str(project), "theos": str(theos),
                   "sdk": str(sdk), "sdk_version": env_info["sdk_version"], "arch_source": plan["arch_source"],
                   "expected_archs": plan["expected_archs"], "scheme_source": plan["scheme_source"],
                   "signing_pipeline": plan["signing"], "build_log": str(log_path),
                   "auto_setup": auto_setup, "local_build": True})
    (out / "BUILD_REPORT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "SHA256SUMS.txt").write_text("{}  {}\n".format(result["sha256"], target_package.name), encoding="utf-8")
    return result


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def add_build_args(parser):
    parser.add_argument("--project", default=".", help="Theos project path; defaults to current directory and safe auto-discovery")
    parser.add_argument("--out", default=None, help="Output directory for DEB, report, checksum and build log")
    parser.add_argument("--arch", default="auto", help="auto, or comma-separated architecture override such as arm64,arm64e")
    parser.add_argument("--scheme", default="auto", choices=("auto", "rootless", "roothide", "rootful"), help="Preserve project scheme by default")
    parser.add_argument("--timeout", type=int, default=1800, help="Build timeout in seconds")
    parser.add_argument("--no-auto-setup", action="store_true", help="Do not install missing host packages or bootstrap Theos")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-first Theos DEB build, signing and verification factory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only build environment check")
    sub.add_parser("bootstrap", help="Install supported host dependencies and prepare Theos")
    add_build_args(sub.add_parser("build", help="Build and verify a Theos DEB"))
    add_build_args(sub.add_parser("auto", help="Auto-prepare environment, build, sign and verify a DEB"))
    verify = sub.add_parser("verify", help="Verify a built DEB and its Mach-O payload")
    verify.add_argument("package")
    verify.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            emit(inspect_environment())
            return 0
        if args.command == "bootstrap":
            report = bootstrap_environment()
            emit(report)
            return 0 if report.get("ok") else 2
        if args.command == "verify":
            emit(verify_package(args.package, out_dir=args.out))
            return 0
        result = build_package(args.project, out_dir=args.out, arch_option=args.arch, scheme_option=args.scheme,
                               timeout=args.timeout, auto_setup=(args.command == "auto" or not args.no_auto_setup))
        emit(result)
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "NO-GO", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
