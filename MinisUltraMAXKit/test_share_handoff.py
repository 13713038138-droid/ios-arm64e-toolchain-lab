"""R5.5 source-level share handoff patch tests; no iOS/device claims."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("patch_share_handoff.py")

FIXTURES = {
    "Shared/SharedContainerStore.swift": """import Foundation
enum SharedContainerStore {
    static func savePendingShare(_ share: PendingShare) {
        guard let defaults = sharedDefaults else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(share) {
            defaults.set(data, forKey: pendingShareKey)
            defaults.synchronize()
        }
    }
}
""",
    "ShareExtension/ShareViewModel.swift": """class ShareViewModel {
    func save() -> Bool {
        SharedContainerStore.savePendingShare(share)
        return true
    }
}
""",
    "ShareExtension/ShareViewController.swift": """class ShareViewController {
            redirectToHostApp()

            // Mark done
    }
""",
    "Shared/ExternalFileImporter.swift": """enum ExternalFileImporter {
        SharedContainerStore.savePendingShare(share)
        importLog.info("saved")
}
""",
}

class ShareHandoffPatchTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.src = self.root / "src/ios"
        for path, contents in FIXTURES.items():
            dest = self.src / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(contents)

    def run_patch(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root)],
                              text=True, capture_output=True)

    def test_patch_propagates_failures_from_both_share_entrypoints(self):
        outcome = self.run_patch()
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        def read(path):
            return (self.src / path).read_text()
        shared = read("Shared/SharedContainerStore.swift")
        self.assertIn("static func savePendingShare(_ share: PendingShare) -> Bool", shared)
        self.assertIn("let directory = sharedFileDirectory", shared)
        self.assertIn("defaults.data(forKey: pendingShareKey) == data", shared)
        self.assertIn("return SharedContainerStore.savePendingShare(share)",
                      read("ShareExtension/ShareViewModel.swift"))
        self.assertIn("one or more attachment files were not staged",
                      read("ShareExtension/ShareViewModel.swift"))
        self.assertIn("extensionContext?.cancelRequest(withError: error)",
                      read("ShareExtension/ShareViewController.swift"))
        self.assertIn("guard SharedContainerStore.savePendingShare(share) else",
                      read("Shared/ExternalFileImporter.swift"))

    def test_drift_is_rejected_without_partial_edits(self):
        broken = self.src / "ShareExtension/ShareViewController.swift"
        broken.write_text(broken.read_text().replace("redirectToHostApp()", "missing()"))
        snapshots = {p: (self.src / p).read_bytes() for p in FIXTURES}
        outcome = self.run_patch()
        self.assertNotEqual(outcome.returncode, 0)
        self.assertIn("NO-GO", outcome.stderr)
        for name, before in snapshots.items():
            self.assertEqual((self.src / name).read_bytes(), before, name)

    def test_second_application_fails_closed(self):
        self.assertEqual(self.run_patch().returncode, 0)
        snapshots = {p: (self.src / p).read_bytes() for p in FIXTURES}
        outcome = self.run_patch()
        self.assertNotEqual(outcome.returncode, 0)
        for name, before in snapshots.items():
            self.assertEqual((self.src / name).read_bytes(), before, name)

if __name__ == "__main__":
    unittest.main()
