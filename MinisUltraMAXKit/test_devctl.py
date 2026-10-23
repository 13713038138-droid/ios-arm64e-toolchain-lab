#!/usr/bin/env python3
import argparse
import importlib.util
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("devctl", HERE / "devctl.py")
devctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(devctl)

def route(task, paths=None):
    output = StringIO()
    with redirect_stdout(output):
        devctl.cmd_route(argparse.Namespace(task=task, path=paths or [], out=None))
    return json.loads(output.getvalue())

class RouteTests(unittest.TestCase):
    def test_r32_abi_v2_selects_apple_ci_gate(self):
        result = route("Stheno R32 ABI v2 Apple/Xcode CI clean build and original verifier")
        ids = {x["id"] for x in result["selected_profiles"]}
        self.assertIn("ios_abi_v2_apple_ci", ids)
        self.assertIn("minis-abi preflight", result["recommended_tools"])
        self.assertIn("minis-abi apple-check", result["recommended_tools"])
        self.assertIn("original-ABI-v2-verifier-output", result["required_gates"])

    def test_ios_reverse_and_build_select_multiple_profiles(self):
        result = route("深逆 SpringBoard arm64e Hook 调用链并编译 RootHide deb")
        ids = {x["id"] for x in result["selected_profiles"]}
        self.assertIn("ios_reverse_engineering", ids)
        self.assertIn("ios_build", ids)
        self.assertIn("minis-bin <IPA|DEB|Mach-O>", result["recommended_tools"])
        self.assertTrue(any("minis-dev-ultra hook --name HookName" in x for x in result["recommended_tools"]))
        self.assertIn("minis-deb auto --project <path> --arch auto", result["recommended_tools"])
        self.assertIn("ABI/PAC-review", result["selected_specialists"])
        self.assertIn("references/ios-reverse-auditor.md", result["selected_references"])
        self.assertEqual(result["risk_level"], "high")

    def test_keyboard_crash_selects_ui_and_crash(self):
        result = route("修复横屏键盘闪退 SIGTRAP")
        ids = {x["id"] for x in result["selected_profiles"]}
        self.assertIn("swift_ui", ids)
        self.assertIn("crash_debug", ids)
        self.assertIn("earliest-causal-error", result["required_gates"])

    def test_python_path_adds_python_runtime(self):
        result = route("fix build test", ["MinisUltraMAXKit/tool.py"])
        self.assertIn("python_runtime", {x["id"] for x in result["selected_profiles"]})

    def test_frontend_and_backend_mix(self):
        result = route("React frontend calls REST API backed by PostgreSQL database")
        ids = {x["id"] for x in result["selected_profiles"]}
        self.assertIn("frontend", ids)
        self.assertIn("backend", ids)

    def test_general_fallback(self):
        result = route("Help me organize a poem")
        self.assertEqual(result["primary_profile"], "general_engineering")
        self.assertEqual(result["risk_level"], "low")

    def test_apelin_on_device_ide_selects_workspace_profile(self):
        result = route("Apelin on-device IDE code editor for jailbreak tweaks")
        self.assertIn("on_device_ide", {x["id"] for x in result["selected_profiles"]})

    def test_toolchain_and_sdk_management_selects_compatibility_profile(self):
        result = route("Automatically configure compiler toolchain and register an iPhoneOS SDK")
        self.assertIn("toolchain_sdk", {x["id"] for x in result["selected_profiles"]})

    def test_persistent_terminal_selects_resumable_session_profile(self):
        result = route("Persistent terminal session should survive app relaunch and resume a long build task")
        self.assertIn("terminal_sessions", {x["id"] for x in result["selected_profiles"]})

    def test_install_and_post_respring_diagnostics_select_profile(self):
        result = route("Install tweak, respring, check load marker and crash symbolication")
        self.assertIn("install_diagnostics", {x["id"] for x in result["selected_profiles"]})

    def test_strict_agent_approval_selects_security_profile(self):
        result = route("Strict mode agent approval before destructive delete or install")
        self.assertIn("agent_approval", {x["id"] for x in result["selected_profiles"]})

    def test_project_template_selects_scaffolder_profile(self):
        result = route("Create a new tweak project from project template and scaffold Makefile")
        self.assertIn("project_templates", {x["id"] for x in result["selected_profiles"]})

    def test_git_transfer_selects_credential_profile(self):
        result = route("Transfer SDK and project files, store GitHub token in keychain")
        self.assertIn("git_transfer", {x["id"] for x in result["selected_profiles"]})

    def test_disassembly_tools_select_profile_without_claiming_presence(self):
        result = route("Disassemble Mach-O with Capstone and assemble with Keystone")
        self.assertIn("binary_tool_extensions", {x["id"] for x in result["selected_profiles"]})
        self.assertTrue(any("only if the matching licensed extension is actually installed" in x
                            for x in result["recommended_tools"]))

    def test_router_does_not_claim_model_or_quota_control(self):
        result = route("optimize token use")
        self.assertTrue(any("does not switch the underlying AI model" in x for x in result["limitations"]))

def scaffold(kind, name, bundle_id, path, scheme="roothide"):
    output = StringIO()
    args = argparse.Namespace(kind=kind, name=name, bundle_id=bundle_id, path=str(path), scheme=scheme, out=None)
    with redirect_stdout(output):
        devctl.cmd_new(args)
    return json.loads(output.getvalue())


class ScaffoldTests(unittest.TestCase):
    def test_creates_rootless_tweak_with_matching_architecture_and_scheme(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "SampleTweak"
            result = scaffold("tweak", "SampleTweak", "com.example.sampletweak", target, "rootless")
            self.assertEqual(result["status"], "CREATED")
            self.assertIn("ARCHS = arm64\n", (target / "Makefile").read_text())
            self.assertIn("THEOS_PACKAGE_SCHEME = rootless\n", (target / "Makefile").read_text())
            self.assertIn("Architecture: iphoneos-arm64\n", (target / "control").read_text())
            self.assertTrue((target / "Tweak.xm").is_file())
            self.assertTrue((target / "SampleTweak.plist").is_file())
            self.assertTrue((target / ".minis-dev-project.json").is_file())
            self.assertIn("%ctor", (target / "Tweak.xm").read_text())
            self.assertNotIn("%hook", (target / "Tweak.xm").read_text())

    def test_creates_roothide_cli_template(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "SampleCLI"
            result = scaffold("cli", "SampleCLI", "com.example.samplecli", target, "roothide")
            self.assertEqual(result["architecture"], "arm64e")
            self.assertIn("ARCHS = arm64e\n", (target / "Makefile").read_text())
            self.assertIn("THEOS_PACKAGE_SCHEME = roothide\n", (target / "Makefile").read_text())
            self.assertIn("Architecture: iphoneos-arm64e\n", (target / "control").read_text())
            self.assertTrue((target / "main.c").is_file())

    def test_creates_minimal_uikit_app_template(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "SampleApp"
            result = scaffold("app", "SampleApp", "com.example.sampleapp", target, "rootless")
            self.assertEqual(result["kind"], "app")
            self.assertIn("APPLICATION_NAME = SampleApp\n", (target / "Makefile").read_text())
            self.assertIn("SampleApp_BUNDLE_ID = com.example.sampleapp\n", (target / "Makefile").read_text())
            self.assertTrue((target / "main.m").is_file())
            self.assertTrue((target / "AppDelegate.h").is_file())
            self.assertTrue((target / "AppDelegate.m").is_file())
            self.assertIn("Section: Applications\n", (target / "control").read_text())

    def test_creates_preferences_bundle_and_loader_entry(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "SamplePrefs"
            scaffold("preferences", "SamplePrefs", "com.example.sampleprefs", target, "rootless")
            self.assertTrue((target / "RootListController.m").is_file())
            self.assertTrue((target / "Root.plist").is_file())
            self.assertTrue((target / "layout/Library/PreferenceLoader/Preferences/SamplePrefs.plist").is_file())
            self.assertIn("com.example.sampleprefs.prefs", (target / "Makefile").read_text())

    def test_refuses_to_overwrite_existing_project(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "Existing"
            target.mkdir()
            (target / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                devctl.cmd_new(argparse.Namespace(kind="cli", name="Existing",
                    bundle_id="com.example.existing", path=str(target), scheme="rootless", out=None))
            self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_rejects_invalid_name_and_bundle_identity(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "NotCreated"
            with self.assertRaisesRegex(ValueError, "invalid project name"):
                devctl.cmd_new(argparse.Namespace(kind="tweak", name="../Escape",
                    bundle_id="com.example.escape", path=str(target), scheme="roothide", out=None))
            with self.assertRaisesRegex(ValueError, "invalid bundle id"):
                devctl.cmd_new(argparse.Namespace(kind="tweak", name="ValidName",
                    bundle_id="com..escape", path=str(target), scheme="roothide", out=None))
            self.assertFalse(target.exists())



def hook_scaffold(name, bundle_id, process, class_name, method, path, scheme="roothide"):
    output = StringIO()
    args = argparse.Namespace(name=name, bundle_id=bundle_id, process=process,
        class_name=class_name, method=method, path=str(path), scheme=scheme, out=None)
    with redirect_stdout(output):
        devctl.cmd_hook(args)
    return json.loads(output.getvalue())


class HookLabTests(unittest.TestCase):
    def test_creates_verified_void_method_passthrough(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "HookProbe"
            result = hook_scaffold("HookProbe", "com.example.hookprobe",
                "com.example.target", "TargetController",
                "- (void)setEnabled:(BOOL)enabled", target, "roothide")
            self.assertEqual(result["status"], "CREATED_TEMPLATE_NOT_RUNTIME_VERIFIED")
            self.assertIn("%hook TargetController", (target / "Tweak.xm").read_text())
            self.assertIn("- (void)setEnabled:(BOOL)enabled {", (target / "Tweak.xm").read_text())
            self.assertIn("%orig;", (target / "Tweak.xm").read_text())
            self.assertIn('"com.example.target"', (target / "HookProbe.plist").read_text())
            meta = json.loads((target / ".minis-dev-project.json").read_text())
            self.assertEqual(meta["target_process_bundle_id"], "com.example.target")
            self.assertIn("pass-through", (target / "README.md").read_text())

    def test_returns_original_value_for_nonvoid_method(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "HookProbe"
            hook_scaffold("HookProbe", "com.example.hookprobe",
                "com.example.target", "TargetController", "- (BOOL)isEnabled",
                target, "rootless")
            self.assertIn("return %orig;", (target / "Tweak.xm").read_text())
            self.assertIn("ARCHS = arm64\n", (target / "Makefile").read_text())

    def test_rejects_method_injection_and_unverified_class_syntax(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for method in ("- (void)run { exit(0); }", "- (void)run;\n%ctor { }", "void run(void)"):
                with self.subTest(method=method):
                    with self.assertRaisesRegex(ValueError, "verified Objective-C method"):
                        devctl.cmd_hook(argparse.Namespace(name="HookProbe",
                            bundle_id="com.example.hookprobe", process="com.example.target",
                            class_name="TargetController", method=method,
                            path=str(base / "not-created"), scheme="roothide", out=None))
            with self.assertRaisesRegex(ValueError, "class name"):
                devctl.cmd_hook(argparse.Namespace(name="HookProbe",
                    bundle_id="com.example.hookprobe", process="com.example.target",
                    class_name="Target; %ctor", method="- (BOOL)isEnabled",
                    path=str(base / "not-created"), scheme="roothide", out=None))
            self.assertFalse((base / "not-created").exists())

    def test_refuses_existing_output_path(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "Existing"
            target.mkdir()
            (target / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                devctl.cmd_hook(argparse.Namespace(name="HookProbe",
                    bundle_id="com.example.hookprobe", process="com.example.target",
                    class_name="TargetController", method="- (BOOL)isEnabled",
                    path=str(target), scheme="roothide", out=None))
            self.assertEqual((target / "keep.txt").read_text(), "keep")


class BinaryTests(unittest.TestCase):
    @staticmethod
    def thin_arm64e(subtype=2):
        return struct.pack("<IiiIIIII", 0xfeedfacf, 0x0100000c, subtype, 2, 0, 0, 0, 0)

    def test_arm64e_thin_header(self):
        result = devctl.macho_header(self.thin_arm64e())
        self.assertEqual(result["kind"], "macho64")
        self.assertEqual(result["architecture"], "arm64e")

    def test_fat_macho_slices(self):
        offset_a, offset_b, slice_size = 64, 128, 32
        data = bytearray(160)
        data[0:8] = struct.pack(">II", 0xcafebabe, 2)
        data[8:28] = struct.pack(">iiIII", 0x0100000c, 2, offset_a, slice_size, 0)
        data[28:48] = struct.pack(">iiIII", 0x0100000c, 0, offset_b, slice_size, 0)
        data[offset_a:offset_a + slice_size] = self.thin_arm64e(2)
        data[offset_b:offset_b + slice_size] = self.thin_arm64e(0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.dylib"
            path.write_bytes(data)
            result = devctl.inspect_macho_file(path)
        self.assertEqual(result["kind"], "fat-macho")
        self.assertEqual(result["slice_count"], 2)
        self.assertEqual(result["slices"][0]["header"]["architecture"], "arm64e")
        self.assertEqual(result["slices"][1]["header"]["architecture"], "arm64")

    def test_fat_macho_rejects_out_of_bounds_slice(self):
        data = bytearray(64)
        data[0:8] = struct.pack(">II", 0xcafebabe, 1)
        data[8:28] = struct.pack(">iiIII", 0x0100000c, 2, 128, 32, 0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.bin"
            path.write_bytes(data)
            result = devctl.inspect_macho_file(path)
        self.assertIn("error", result["slices"][0])

if __name__ == "__main__":
    unittest.main()
