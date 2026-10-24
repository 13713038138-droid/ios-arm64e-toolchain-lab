"""Genuine IPA/DEB archive intake tests (no external SDK required)."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

from test_reverse_lab import fixture
import reverse_intake as ri

def ar_member(name,data):
    header=(name+"/").ljust(16)
    fields=header+str(0).ljust(12)+str(0).ljust(6)+str(0).ljust(6)+str(0o100644).ljust(8)+str(len(data)).ljust(10)
    return fields.encode("ascii")+bytes([0x60,0x0a])+data+(b"\n" if len(data)%2 else b"")

def make_deb(member_name,blob):
    tar_buf=io.BytesIO()
    with tarfile.open(fileobj=tar_buf,mode="w:xz") as tar:
        info=tarfile.TarInfo(member_name)
        info.size=len(blob)
        tar.addfile(info,io.BytesIO(blob))
    return b"!<arch>\n"+ar_member("debian-binary",b"2.0\n")+ar_member("data.tar.xz",tar_buf.getvalue())

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_ipa_single_binary_analyzes_real_swift_type(self):
        ipa=self.root/"MinisMAX.ipa"
        with zipfile.ZipFile(ipa,"w",compression=zipfile.ZIP_DEFLATED) as out:
            out.writestr("Payload/MinisMAX.app/MinisMAX",fixture())
            out.writestr("Payload/MinisMAX.app/Info.plist",b"not-an-executable")
        result=ri.inspect(ipa,search="WidgetCore")
        self.assertEqual(result["status"],"analyzed")
        self.assertEqual(result["selected_member"],"Payload/MinisMAX.app/MinisMAX")
        self.assertEqual(result["analysis"]["slices"][0]["swift_nominal_types"][0]["name"],"WidgetCore")

    def test_deb_tweak_dylib_works_without_shell(self):
        deb=self.root/"Stheno.deb"
        deb.write_bytes(make_deb("./Library/MobileSubstrate/DynamicLibraries/Stheno.dylib",fixture()))
        result=ri.inspect(deb)
        self.assertEqual(result["status"],"analyzed")
        self.assertEqual(result["archive_kind"],"deb")
        self.assertEqual(result["analysis"]["slices"][0]["architecture"],"arm64e")

    def test_two_ipa_binaries_require_specific_member(self):
        ipa=self.root/"twobin.ipa"
        with zipfile.ZipFile(ipa,"w") as out:
            out.writestr("Payload/Minis.app/Minis",fixture())
            out.writestr("Payload/Minis.app/Frameworks/Agent.framework/Agent",fixture())
        result=ri.inspect(ipa)
        self.assertEqual(result["status"],"selection_required")
        self.assertEqual(result["candidate_count"],2)
        specific=ri.inspect(ipa,"Payload/Minis.app/Frameworks/Agent.framework/Agent")
        self.assertEqual(specific["status"],"analyzed")

    def test_ipa_malicious_parent_member_rejected(self):
        ipa=self.root/"evil.ipa"
        with zipfile.ZipFile(ipa,"w") as out:
            out.writestr("../Stheno.dylib",fixture())
        with self.assertRaises(ri.IntakeError): ri.inspect(ipa)

    def test_deb_symlink_target_not_analyzed(self):
        tar_buf=io.BytesIO()
        with tarfile.open(fileobj=tar_buf,mode="w:xz") as archive:
            entry=tarfile.TarInfo("./usr/lib/Stheno.dylib")
            entry.type=tarfile.SYMTYPE
            entry.linkname="../../etc/passwd"
            archive.addfile(entry)
        deb=self.root/"linked.deb"
        deb.write_bytes(b"!<arch>\n"+ar_member("data.tar.xz",tar_buf.getvalue()))
        self.assertEqual(ri.inspect(deb)["status"],"selection_required")
        with self.assertRaises(ri.IntakeError):
            ri.inspect(deb,"./usr/lib/Stheno.dylib")

    def test_archive_is_unchanged_by_read_only_inspection(self):
        ipa=self.root/"safe.ipa"
        with zipfile.ZipFile(ipa,"w") as out:
            out.writestr("Payload/Minis.app/Minis",fixture())
        before=ipa.read_bytes()
        p=subprocess.run([sys.executable,str(Path(ri.__file__)),"analyze",str(ipa)],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(ipa.read_bytes(),before)
        data=json.loads(p.stdout)
        self.assertEqual(data["status"],"analyzed")

if __name__=="__main__": unittest.main()
