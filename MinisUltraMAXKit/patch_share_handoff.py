#!/usr/bin/env python3
"""Repair share handoff result propagation in the pinned OpenMinis source.

Run AFTER patch_ips_sigtrap.py, BEFORE the Xcode build.
The app/extension App Group entitlement must be signed separately.
This code never mutates installed apps or user data.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: python3 patch_share_handoff.py /path/to/pinned/OpenMinis")
root = Path(sys.argv[1]).resolve()
src = root / "src/ios"

def replace_one(relative, old, new):
    file = src / relative
    if not file.is_file():
        raise RuntimeError(f"NO-GO: missing upstream file {relative}")
    value = file.read_text(encoding="utf-8")
    if value.count(old) != 1:
        raise RuntimeError(f"NO-GO: source drift at {relative} (matches {value.count(old)})")
    file.write_text(value.replace(old, new, 1), encoding="utf-8")

replace_one("Shared/SharedContainerStore.swift",
"""    static func savePendingShare(_ share: PendingShare) {
        guard let defaults = sharedDefaults else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(share) {
            defaults.set(data, forKey: pendingShareKey)
            defaults.synchronize()
        }
    }""",
"""    @discardableResult
    static func savePendingShare(_ share: PendingShare) -> Bool {
        // A non-nil UserDefaults suite is NOT proof that an app extension and
        // the host can exchange files. Reject a missing shared container.
        guard let defaults = sharedDefaults, let directory = sharedFileDirectory else {
            NSLog("[Share] Cannot persist pending share: shared App Group unavailable")
            return false
        }
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            NSLog("[Share] Cannot create shared directory: %@", error.localizedDescription)
            return false
        }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let data = try? encoder.encode(share) else { return false }
        defaults.set(data, forKey: pendingShareKey)
        _ = defaults.synchronize()
        // Verify the record is visible to the same process. Cross-process
        // visibility still requires a real device test.
        return defaults.data(forKey: pendingShareKey) == data
    }""")

replace_one("ShareExtension/ShareViewModel.swift",
"""        SharedContainerStore.savePendingShare(share)
        return true""",
"""        guard let directory = SharedContainerStore.sharedFileDirectory else {
            NSLog("[ShareExt] ERROR: shared App Group directory unavailable")
            return false
        }
        let attachments = items.filter { $0.kind == .attachment }
        guard attachments.allSatisfy({
            FileManager.default.fileExists(atPath: directory.appendingPathComponent($0.value).path)
        }) else {
            NSLog("[ShareExt] ERROR: one or more attachment files were not staged")
            return false
        }
        return SharedContainerStore.savePendingShare(share)""")

replace_one("ShareExtension/ShareViewController.swift",
"""            redirectToHostApp()

            // Mark done""",
"""            guard saved else {
                // Do not tell iOS or the user that a failed handoff succeeded.
                NSLog("[ShareExt] ERROR: handoff failed; refusing host redirect")
                processingDone = true
                let error = NSError(domain: "MinisShare", code: 1001,
                    userInfo: [NSLocalizedDescriptionKey:
                        "MinisMAX could not access its shared file container"])
                extensionContext?.cancelRequest(withError: error)
                return
            }
            redirectToHostApp()

            // Mark done""")

replace_one("Shared/ExternalFileImporter.swift",
"""        SharedContainerStore.savePendingShare(share)
        importLog.info""",
"""        guard SharedContainerStore.savePendingShare(share) else {
            try? fm.removeItem(at: dest)
            importLog.error("[Share] ingest: failed to persist pending share")
            return false
        }
        importLog.info""")

print("PASS: host and Share Extension now verify persisted share results")
print("NOT VERIFIED: iOS App Group entitlement, cross-process handoff and device acceptance")
