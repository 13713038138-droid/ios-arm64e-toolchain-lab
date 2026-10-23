#!/usr/bin/env python3
import base64
import importlib.util
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("deb_factory", HERE / "deb_factory.py")
factory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(factory)


def thin_macho(subtype=2, signed=True):
    header = struct.pack("<IiiIIIII", 0xfeedfacf, 0x0100000c, subtype, 6, 1, 16, 0, 0)
    if signed:
        command = struct.pack("<IIII", 0x1d, 16, 0x100, 0x20)
        return header + command + (b"\0" * (0x120 - len(header) - len(command)))
    return struct.pack("<IiiIIIII", 0xfeedfacf, 0x0100000c, subtype, 6, 0, 0, 0, 0) + (b"\0" * 8)


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        (self.project / "control").write_text("Package: com.example.test\nVersion: 1.0\nArchitecture: iphoneos-arm64\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_makefile_arch_and_roothide_scheme_are_preserved(self):
        (self.project / "Makefile").write_text("ARCHS = arm64e\nTHEOS_PACKAGE_SCHEME = roothide\nTARGET_CODESIGN = ldid\nTARGET_CODESIGN_FLAGS = -S\n")
        plan = factory.build_plan(self.project, sdk=Path("/tmp/iPhoneOS16.5.sdk"))
        self.assertEqual(plan["expected_archs"], ["arm64e"])
        self.assertEqual(plan["scheme_source"], "project Makefile; preserved")
        self.assertNotIn("ARCHS=arm64 arm64e", plan["make_args"])
        self.assertFalse(any(x.startswith("THEOS_PACKAGE_SCHEME=") for x in plan["make_args"]))
        self.assertEqual(plan["signing"], "Theos TARGET_CODESIGN pipeline; ldid")

    def test_auto_arch_uses_modern_dual_arch_default_without_overriding_makefile(self):
        (self.project / "Makefile").write_text("include $(THEOS)/makefiles/common.mk\n")
        plan = factory.build_plan(self.project, sdk=Path("/tmp/iPhoneOS16.5.sdk"))
        self.assertEqual(plan["expected_archs"], ["arm64", "arm64e"])
        self.assertFalse(any(x.startswith("ARCHS=") for x in plan["make_args"]))
        self.assertIn("TARGET_CODESIGN=ldid", plan["make_args"])
        self.assertIn("TARGET_CODESIGN_FLAGS=-S", plan["make_args"])

    def test_explicit_arch_override(self):
        (self.project / "Makefile").write_text("ARCHS = arm64e\n")
        plan = factory.build_plan(self.project, arch_option="arm64,arm64e", sdk=Path("/tmp/iPhoneOS16.5.sdk"))
        self.assertEqual(plan["expected_archs"], ["arm64", "arm64e"])
        self.assertIn("ARCHS=arm64 arm64e", plan["make_args"])

    def test_legacy_deployment_does_not_require_arm64e_by_default(self):
        (self.project / "Makefile").write_text("TARGET = iphone:clang:16.5:9.0\n")
        plan = factory.build_plan(self.project, sdk=Path("/tmp/iPhoneOS16.5.sdk"))
        self.assertEqual(plan["expected_archs"], ["arm64"])

    def test_rootful_clears_scheme_instead_of_passing_invalid_value(self):
        (self.project / "Makefile").write_text("THEOS_PACKAGE_SCHEME = roothide\n")
        plan = factory.build_plan(self.project, scheme_option="rootful", sdk=Path("/tmp/iPhoneOS16.5.sdk"))
        self.assertIn("THEOS_PACKAGE_SCHEME=", plan["make_args"])
        self.assertNotIn("THEOS_PACKAGE_SCHEME=rootful", plan["make_args"])

    def test_custom_signer_without_flags_is_no_go(self):
        (self.project / "Makefile").write_text("TARGET_CODESIGN = codesign\n")
        with self.assertRaisesRegex(RuntimeError, "without TARGET_CODESIGN_FLAGS"):
            factory.build_plan(self.project, sdk=Path("/tmp/iPhoneOS16.5.sdk"))

    def test_project_discovery_from_parent(self):
        nested = self.project / "src" / "feature"
        nested.mkdir(parents=True)
        (self.project / "Makefile").write_text("ARCHS = arm64e\n")
        result, candidates = factory.discover_project(nested)
        self.assertEqual(result, self.project.resolve())
        self.assertEqual(candidates, [])

    def test_build_rejects_non_project_before_attempting_bootstrap(self):
        with self.assertRaisesRegex(RuntimeError, "Theos Makefile"):
            factory.build_package(self.project, auto_setup=False)


class MachOTests(unittest.TestCase):
    def test_signed_arm64e_thin_binary(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.dylib"
            path.write_bytes(thin_macho(2, True))
            result = factory.macho_slices(path)
        self.assertEqual(result[0]["architecture"], "arm64e")
        self.assertTrue(result[0]["signed"])

    def test_unsigned_binary_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.dylib"
            path.write_bytes(thin_macho(2, False))
            result = factory.macho_slices(path)
        self.assertEqual(result[0]["architecture"], "arm64e")
        self.assertFalse(result[0]["signed"])

    def test_universal_arm64_and_arm64e(self):
        one = thin_macho(2, True)
        two = thin_macho(0, True)
        offset_a, offset_b = 64, 64 + len(one)
        data = bytearray(offset_b + len(two))
        data[:8] = struct.pack(">II", 0xcafebabe, 2)
        data[8:28] = struct.pack(">iiIII", 0x0100000c, 2, offset_a, len(one), 0)
        data[28:48] = struct.pack(">iiIII", 0x0100000c, 0, offset_b, len(two), 0)
        data[offset_a:offset_a + len(one)] = one
        data[offset_b:offset_b + len(two)] = two
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "universal.dylib"
            path.write_bytes(data)
            result = factory.macho_slices(path)
        self.assertEqual({x["architecture"] for x in result}, {"arm64", "arm64e"})
        self.assertTrue(all(x["signed"] for x in result))

    def test_bad_universal_offsets_are_rejected(self):
        data = bytearray(64)
        data[:8] = struct.pack(">II", 0xcafebabe, 1)
        data[8:28] = struct.pack(">iiIII", 0x0100000c, 2, 128, 32, 0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.dylib"
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "invalid universal slice bounds"):
                factory.macho_slices(path)

    def test_little_endian_fat64_arm64e(self):
        one = thin_macho(2, True)
        offset = 64
        data = bytearray(offset + len(one))
        data[:8] = struct.pack("<II", 0xcafebabf, 1)
        data[8:40] = struct.pack("<iiQQII", 0x0100000c, 2, offset, len(one), 0, 0)
        data[offset:offset + len(one)] = one
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "little-fat64.dylib"
            path.write_bytes(data)
            result = factory.macho_slices(path)
        self.assertEqual(result[0]["architecture"], "arm64e")
        self.assertTrue(result[0]["signed"])

    def test_sha256_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "file.bin"
            path.write_bytes(b"abc")
            self.assertEqual(factory.file_sha256(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


    def test_verify_package_checks_metadata_architecture_and_signature(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fakebin = root / "bin"
            fakebin.mkdir()
            fake = fakebin / "dpkg-deb"
            fake.write_text("""#!/usr/bin/env python3
import base64, os, pathlib, sys
args = sys.argv[1:]
if args[0] == "-f":
    print("com.example.test")
    print("1.0")
    print("iphoneos-arm64")
elif args[0] == "--contents":
    print("./Library/MobileSubstrate/DynamicLibraries/Test.dylib")
elif args[0] == "-x":
    dest = pathlib.Path(args[2])
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "Library/MobileSubstrate/DynamicLibraries/Test.dylib"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(os.environ["TEST_MACHO_B64"]))
else:
    raise SystemExit(2)
""", encoding="utf-8")
            fake.chmod(0o755)
            package = root / "sample.deb"
            package.write_bytes(b"synthetic package fixture")
            env_path = str(fakebin) + os.pathsep + os.environ.get("PATH", "")
            with patch.dict(os.environ, {"PATH": env_path, "TEST_MACHO_B64": base64.b64encode(thin_macho(2, True)).decode("ascii")}):
                result = factory.verify_package(package, expected_archs=["arm64e"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["package"], "com.example.test")
            self.assertEqual(result["macho_files"][0]["architectures"], ["arm64e"])
            self.assertTrue(result["macho_files"][0]["all_slices_signed"])

    def test_verify_package_rejects_unsigned_macho(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fakebin = root / "bin"
            fakebin.mkdir()
            fake = fakebin / "dpkg-deb"
            fake.write_text("""#!/usr/bin/env python3
import base64, os, pathlib, sys
args = sys.argv[1:]
if args[0] == "-f":
    print("com.example.test")
    print("1.0")
    print("iphoneos-arm64")
elif args[0] == "--contents":
    print("./Library/MobileSubstrate/DynamicLibraries/Test.dylib")
elif args[0] == "-x":
    dest = pathlib.Path(args[2])
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "Library/MobileSubstrate/DynamicLibraries/Test.dylib"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(os.environ["TEST_MACHO_B64"]))
else:
    raise SystemExit(2)
""", encoding="utf-8")
            fake.chmod(0o755)
            package = root / "sample.deb"
            package.write_bytes(b"synthetic package fixture")
            env_path = str(fakebin) + os.pathsep + os.environ.get("PATH", "")
            with patch.dict(os.environ, {"PATH": env_path, "TEST_MACHO_B64": base64.b64encode(thin_macho(2, False)).decode("ascii")}):
                with self.assertRaisesRegex(RuntimeError, "without LC_CODE_SIGNATURE"):
                    factory.verify_package(package, expected_archs=["arm64e"])

if __name__ == "__main__":
    unittest.main()
