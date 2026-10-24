"""Verify ReverseLab's actual LLVM disassembler adapter and safety fallback."""
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import mock
import unittest
import reverse_disasm as real

class NativeDisasmTests(unittest.TestCase):
    def test_absent_llvm_never_claims_full_decode(self):
        with mock.patch("reverse_disasm.executable", return_value=None):
            instructions,problem=real.decode(b"\0"*128,0,128,0,12)
        self.assertEqual(instructions,[])
        self.assertIn("not installed",problem)

    def test_bounded_parser_input_rejects_oversized_and_invalid(self):
        with mock.patch("reverse_disasm.executable",return_value="/bin/true"):
            out,error=real.decode(b"\0"*64,0,real.MAX_DISASM_BYTES+1,0,12)
            self.assertEqual(out,[])
            self.assertIn("size",error)
            out,error=real.decode(b"\0"*64,0,64,0,129)
            self.assertEqual(out,[])
            self.assertIn("range",error)

    def test_timeout_fails_closed(self):
        with mock.patch("reverse_disasm.executable",return_value="/usr/bin/llvm-objdump"):
            with mock.patch("reverse_disasm.subprocess.run",side_effect=subprocess.TimeoutExpired(cmd=["llvm-objdump"],timeout=9)):
                out,error=real.decode(b"\0"*64,0,64,0,4)
        self.assertEqual(out,[])
        self.assertIn("time limit",error)

    @unittest.skipUnless(real.executable() and shutil.which("clang"),
                         "real LLVM compiler and objdump not installed")
    def test_genuine_clang_arm64_macho_disassembly(self):
        with tempfile.TemporaryDirectory() as directory:
            src=Path(directory)/"arm.c"
            obj=Path(directory)/"arm.o"
            src.write_text("int plus_one(int a) { return a + 1; }\n")
            result=subprocess.run([shutil.which("clang"),"-target","arm64-apple-ios16.0",
                     "-c",str(src),"-o",str(obj)],capture_output=True,timeout=20)
            if result.returncode:
                self.skipTest("toolchain lacks arm64 Apple object generation")
            data=obj.read_bytes()
            self.assertEqual(data[:4],b"\xcf\xfa\xed\xfe")
            out,problem=real.decode(data,0,len(data),0,32)
            self.assertIsNone(problem)
            self.assertTrue(any(row["mnemonic"]=="ret" for row in out),out)
            self.assertTrue(any(row["mnemonic"] in ("add","ldr","str") for row in out),out)

if __name__=="__main__":unittest.main()
