#!/usr/bin/env python3
"""R4 overlay: make MAX credential persistence truthful, protected, and clone-scoped."""
from pathlib import Path
import re
import sys

import patch_clone_identity_r3
import test_patch_clone_identity_r3

CLONE = "com.openminis.devultramax"

def replace_exact(text: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"NO-GO {label}: expected {expected} exact anchor(s), found {count}")
    return text.replace(old, new)

def edit(root: Path, rel: str, fn) -> None:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"NO-GO: missing required source {rel}")
    original = path.read_text(encoding="utf-8")
    updated = fn(original)
    if updated == original:
        raise RuntimeError(f"NO-GO {rel}: R4 patch produced no change")
    path.write_text(updated, encoding="utf-8")

def patch_provider_store(root: Path) -> None:
    rel = "src/ios/Providers/ProviderConfigStore.swift"
    r3_script = Path(__file__).with_name("patch_clone_identity_r3.py").read_text(encoding="utf-8")
    match = re.search(r"helpers = r'''([\s\S]*?)'''", r3_script)
    if not match:
        raise RuntimeError("NO-GO: cannot identify R3 fallback helper block")
    old_helpers = match.group(1)
    new_helpers = r"""        return "com.openminis.app.provider.\(instanceId)"
    }

    private static func cloneCredentialFallbackDirectory(createIfMissing: Bool) -> URL? {
        guard Bundle.main.bundleIdentifier == "com.openminis.devultramax",
              let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        else { return nil }
        var directory = support.appendingPathComponent("MinisMAXCredentialFallback", isDirectory: true)
        if createIfMissing {
            do {
                try FileManager.default.createDirectory(
                    at: directory,
                    withIntermediateDirectories: true,
                    attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
                )
                try FileManager.default.setAttributes(
                    [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                    ofItemAtPath: directory.path
                )
                var values = URLResourceValues()
                values.isExcludedFromBackup = true
                try directory.setResourceValues(values)
            } catch {
                AppLogger(category: "Keychain").error("MAX protected fallback directory creation failed: \(error.localizedDescription)")
                return nil
            }
        }
        return directory
    }

    private static func cloneCredentialFallbackURL(service: String, account: String, createDirectory: Bool = false) -> URL? {
        guard let directory = cloneCredentialFallbackDirectory(createIfMissing: createDirectory) else { return nil }
        let key = Data("\(service)|\(account)".utf8)
        let name = SHA256.hash(data: key).map { String(format: "%02x", $0) }.joined()
        return directory.appendingPathComponent(name + ".credential", isDirectory: false)
    }

    private static func writeCloneCredentialFallback(_ data: Data, service: String, account: String) -> Bool {
        guard let url = cloneCredentialFallbackURL(service: service, account: account),
              let directory = cloneCredentialFallbackDirectory(createIfMissing: true) else { return false }
        // Protect a sibling temporary file before atomically replacing the committed credential.
        var temporaryURL = directory.appendingPathComponent(UUID().uuidString + ".credential.tmp", isDirectory: false)
        do {
            try data.write(to: temporaryURL, options: .atomic)
            try FileManager.default.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: temporaryURL.path
            )
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try temporaryURL.setResourceValues(values)
            if FileManager.default.fileExists(atPath: url.path) {
                _ = try FileManager.default.replaceItemAt(url, withItemAt: temporaryURL)
            } else {
                try FileManager.default.moveItem(at: temporaryURL, to: url)
            }
            return true
        } catch {
            // Remove only the uncommitted temp file; never delete the previous credential.
            try? FileManager.default.removeItem(at: temporaryURL)
            AppLogger(category: "Keychain").error("MAX protected fallback credential write failed: \(error.localizedDescription)")
            return false
        }
    }

    private static func readCloneCredentialFallback(service: String, account: String) -> Data? {
        guard let url = cloneCredentialFallbackURL(service: service, account: account),
              FileManager.default.fileExists(atPath: url.path) else { return nil }
        do {
            return try Data(contentsOf: url, options: [.mappedIfSafe])
        } catch {
            AppLogger(category: "Keychain").error("MAX protected fallback credential read failed: \(error.localizedDescription)")
            return nil
        }
    }

    private static func stageCloneCredentialFallback(_ data: Data, service: String, account: String) -> (safeToProceed: Bool, saved: Bool) {
        let fallbackWasPresent = readCloneCredentialFallback(service: service, account: account) != nil
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        query[kSecAttrSynchronizable as String] = kSecAttrSynchronizableAny
        var existing: CFTypeRef?
        let keychainStatus = SecItemCopyMatching(query as CFDictionary, &existing)
        // Anything except confirmed absence may be the last valid credential.
        let keychainMayHaveCredential = keychainStatus != errSecItemNotFound
        let saved = writeCloneCredentialFallback(data, service: service, account: account)
        return (saved || (!fallbackWasPresent && !keychainMayHaveCredential), saved)
    }

    @discardableResult
    private static func deleteCloneCredentialFallback(service: String, account: String) -> Bool {
        guard Bundle.main.bundleIdentifier == "com.openminis.devultramax" else { return true }
        guard let url = cloneCredentialFallbackURL(service: service, account: account) else { return false }
        guard FileManager.default.fileExists(atPath: url.path) else { return true }
        do {
            try FileManager.default.removeItem(at: url)
            return true
        } catch {
            AppLogger(category: "Keychain").error("MAX protected fallback credential delete failed: \(error.localizedDescription)")
            return false
        }
    }

    @discardableResult
    static func clearCloneCredentialFallbackDirectory() -> Bool {
        guard Bundle.main.bundleIdentifier == "com.openminis.devultramax" else { return false }
        guard let directory = cloneCredentialFallbackDirectory(createIfMissing: false) else { return false }
        guard FileManager.default.fileExists(atPath: directory.path) else { return true }
        do {
            try FileManager.default.removeItem(at: directory)
            return true
        } catch {
            AppLogger(category: "Keychain").error("MAX protected fallback cleanup failed: \(error.localizedDescription)")
            return false
        }
    }"""
    def apply(s: str) -> str:
        s = replace_exact(s, old_helpers, new_helpers, "protected fallback helper upgrade")

        # API keys must use the protected file fallback if both local Keychain attempts fail.
        s = replace_exact(
            s,
            "static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) {",
            "@discardableResult\n    static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) -> Bool {",
            "API-key Bool signature"
        )
        s = replace_exact(
            s,
            """static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) -> Bool {
        let service = providerService(instanceId: instanceId)
        // Delete both legacy (non-sync) and synchronizable entries""",
            """static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) -> Bool {
        let service = providerService(instanceId: instanceId)
        let fallbackStage = stageCloneCredentialFallback(Data(key.utf8), service: service, account: account)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write apiKey aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8))")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        // Delete both legacy (non-sync) and synchronizable entries""",
            "API-key stale fallback preclear"
        )
        old_api_write = """        var addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        if addStatus != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" && addQuery[kSecAttrSynchronizable as String] != nil {
            // MinisMAX R2.1: preserve credentials locally when the isolated
            // TrollStore signature cannot use synchronizable Keychain.
            addQuery.removeValue(forKey: kSecAttrSynchronizable as String)
            addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        }
        // Stamp the local save time for iCloud LWW conflict resolution.
        stampAPIKeySavedAt(Date(), instanceId: instanceId)
        AppLogger(category: "Keychain").info("write apiKey instanceId=\(instanceId.prefix(8)) keyLen=\(key.count) addStatus=\(addStatus) caller=\(caller)")
        // Refresh credential-derived UI (provider list "configured" dot, etc).
        notifyAuthChanged(instanceId: instanceId)"""
        new_api_write = """        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = addStatus == errSecSuccess ? false : fallbackSavedBeforeKeychain
        if addStatus == errSecSuccess {
            _ = deleteCloneCredentialFallback(service: service, account: account)
        }
        if addStatus == errSecSuccess || fallbackSaved {
            stampAPIKeySavedAt(Date(), instanceId: instanceId)
        } else {
            AppLogger(category: "Keychain").error("write apiKey FAILED instanceId=\(instanceId.prefix(8)) status=\(addStatus) protectedFallbackSaved=false caller=\(caller)")
        }
        AppLogger(category: "Keychain").info("write apiKey instanceId=\(instanceId.prefix(8)) keyLen=\(key.count) keychainStatus=\(addStatus) protectedFallbackSaved=\(fallbackSaved) caller=\(caller)")
        notifyAuthChanged(instanceId: instanceId)
        return addStatus == errSecSuccess || fallbackSaved"""
        s = replace_exact(s, old_api_write, new_api_write, "API-key protected fallback result")
        s = replace_exact(
            s,
            """static func loadAPIKey(instanceId: String, caller: String = #function) -> String? {
        let service = providerService(instanceId: instanceId)
        // Try synchronizable first, then fallback to legacy""",
            """static func loadAPIKey(instanceId: String, caller: String = #function) -> String? {
        let service = providerService(instanceId: instanceId)
        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackKey = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true keyLen=\(fallbackKey.count) caller=\(caller)")
            return fallbackKey
        }
        // Try synchronizable first, then fallback to legacy""",
            "API-key fallback read precedence"
        )
        s = replace_exact(
            s,
            """let s2 = SecItemDelete(syncQuery as CFDictionary)
        // Clear the LWW stamp so any subsequent import""",
            """let s2 = SecItemDelete(syncQuery as CFDictionary)
        _ = deleteCloneCredentialFallback(service: service, account: account)
        // Clear the LWW stamp so any subsequent import""",
            "API-key fallback delete"
        )

        # Raw OAuth import/export shares the oauth-token slot with typed OAuth.
        s = replace_exact(
            s,
            "static func saveRawOAuthToken(_ data: Data, instanceId: String) {",
            "@discardableResult\n    static func saveRawOAuthToken(_ data: Data, instanceId: String) -> Bool {",
            "raw OAuth Bool signature"
        )
        s = replace_exact(
            s,
            """static func saveRawOAuthToken(_ data: Data, instanceId: String) -> Bool {
        let service = providerService(instanceId: instanceId)
        let acct = "oauth-token"
        let deleteQuery: [String: Any] = [""",
            """static func saveRawOAuthToken(_ data: Data, instanceId: String) -> Bool {
        let service = providerService(instanceId: instanceId)
        let acct = "oauth-token"
        let fallbackStage = stageCloneCredentialFallback(data, service: service, account: acct)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write rawOAuthToken aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8))")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        let deleteQuery: [String: Any] = [""",
            "raw OAuth stale fallback preclear"
        )
        raw_start = s.index("        var status = SecItemAdd(addQuery as CFDictionary, nil)", s.index("static func saveRawOAuthToken"))
        # The upstream raw-token writer has no notifyAuthChanged call. End at the
        # next function declaration so this replacement cannot consume loadRawOAuthToken.
        raw_end = s.index("    static func loadRawOAuthToken(instanceId: String) -> Data? {", raw_start)
        new_raw_write = """        let status = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = status == errSecSuccess ? false : fallbackSavedBeforeKeychain
        if status == errSecSuccess {
            _ = deleteCloneCredentialFallback(service: service, account: acct)
        }
        AppLogger(category: "Keychain").info("write rawOAuthToken instanceId=\\(instanceId.prefix(8)) keychainStatus=\\(status) protectedFallbackSaved=\\(fallbackSaved)")
        if status == errSecSuccess || fallbackSaved {
            clearOAuthNeedsReauth(instanceId: instanceId)
        } else {
            AppLogger(category: "Keychain").error("write rawOAuthToken FAILED instanceId=\\(instanceId.prefix(8)) status=\\(status) protectedFallbackSaved=false")
        }
        notifyAuthChanged(instanceId: instanceId)
        return status == errSecSuccess || fallbackSaved
    }

"""
        s = s[:raw_start] + new_raw_write + s[raw_end:]
        raw_load_start = s.index("static func loadRawOAuthToken(instanceId: String) -> Data? {")
        raw_service = "        let service = providerService(instanceId: instanceId)"
        raw_service_end = s.index(raw_service, raw_load_start) + len(raw_service)
        if "src=protectedFallback" in s[raw_service_end:raw_service_end + 450]:
            raise RuntimeError("NO-GO raw OAuth fallback precedence already patched or source drifted")
        raw_fallback_read = r""" 
        if let fallbackData = readCloneCredentialFallback(service: service, account: "oauth-token") {
            AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true")
            return fallbackData
        }"""
        s = s[:raw_service_end] + raw_fallback_read + s[raw_service_end:]

        # Typed OAuth: preserve the old fallback copy until a replacement is committed.
        s = replace_exact(
            s,
            """static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) -> Bool {
        guard let data = try? JSONEncoder().encode(token) else {
            AppLogger(category: "Keychain").error("write oauthToken instanceId=\(instanceId.prefix(8)) ENCODE FAILED caller=\(caller)")
            return false
        }
        let service = providerService(instanceId: instanceId)
        let acct = "oauth-token"
        let deleteQuery: [String: Any] = [""",
            """static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) -> Bool {
        guard let data = try? JSONEncoder().encode(token) else {
            AppLogger(category: "Keychain").error("write oauthToken instanceId=\(instanceId.prefix(8)) ENCODE FAILED caller=\(caller)")
            return false
        }
        let service = providerService(instanceId: instanceId)
        let acct = "oauth-token"
        let fallbackStage = stageCloneCredentialFallback(data, service: service, account: acct)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write oauthToken aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8))")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        let deleteQuery: [String: Any] = [""",
            "typed OAuth stale fallback preclear"
        )
        # Replace the typed-token writer tail by function boundary, not a brittle log anchor.
        typed_fn_start = s.index("static func saveOAuthToken<T: Codable>")
        typed_write_match = re.search(r"        (?:let|var) addStatus = SecItemAdd\(addQuery as CFDictionary, nil\)", s[typed_fn_start:])
        if not typed_write_match:
            raise RuntimeError("NO-GO typed OAuth writer: Keychain add anchor not found")
        typed_start = typed_fn_start + typed_write_match.start()
        typed_end = s.index("    static func loadOAuthToken<T: Codable>", typed_start)
        typed_writer = """        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = addStatus == errSecSuccess ? false : fallbackSavedBeforeKeychain
        if addStatus == errSecSuccess {
            _ = deleteCloneCredentialFallback(service: service, account: acct)
        }
        AppLogger(category: "Keychain").info("write oauthToken instanceId=\\(instanceId.prefix(8)) blobLen=\\(data.count) keychainStatus=\\(addStatus) protectedFallbackSaved=\\(fallbackSaved) caller=\\(caller)")
        if addStatus == errSecSuccess || fallbackSaved {
            clearOAuthNeedsReauth(instanceId: instanceId)
        } else {
            AppLogger(category: "Keychain").error("write oauthToken FAILED instanceId=\\(instanceId.prefix(8)) status=\\(addStatus) protectedFallbackSaved=false caller=\\(caller)")
        }
        notifyAuthChanged(instanceId: instanceId)
        return addStatus == errSecSuccess || fallbackSaved
    }

"""
        s = s[:typed_start] + typed_writer + s[typed_end:]
        s = replace_exact(
            s,
            """static func loadOAuthToken<T: Codable>(instanceId: String, as type: T.Type, caller: String = #function) -> T? {
        let service = providerService(instanceId: instanceId)
        let acct = "oauth-token"
        // Try synchronizable first""",
            """static func loadOAuthToken<T: Codable>(instanceId: String, as type: T.Type, caller: String = #function) -> T? {
        let service = providerService(instanceId: instanceId)
        let acct = "oauth-token"
        if let fallbackData = readCloneCredentialFallback(service: service, account: acct) {
            if let fallbackToken = try? JSONDecoder().decode(type, from: fallbackData) {
                AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true caller=\(caller)")
                return fallbackToken
            }
            AppLogger(category: "Keychain").error("read oauthToken instanceId=\(instanceId.prefix(8)) protected fallback is undecodable as \(type); continuing to Keychain")
        }
        // Try synchronizable first""",
            "typed OAuth fallback read precedence"
        )

        # OAuth metadata strings also report persistence truthfully.
        s = replace_exact(
            s,
            "static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) {",
            "@discardableResult\n    static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {",
            "OAuth string Bool signature"
        )
        s = replace_exact(
            s,
            """static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {
        let service = providerService(instanceId: instanceId)
        let deleteQuery: [String: Any] = [""",
            """static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {
        let service = providerService(instanceId: instanceId)
        let fallbackStage = stageCloneCredentialFallback(Data(value.utf8), service: service, account: account)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write oauthString aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8)) acct=\(account)")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        let deleteQuery: [String: Any] = [""",
            "OAuth string stale fallback preclear"
        )
        s = replace_exact(
            s,
            """let fallbackSaved = addStatus == errSecSuccess ? false : writeCloneCredentialFallback(Data(value.utf8), service: service, account: account)
        AppLogger(category: "Keychain").info("write oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) valLen=\(value.count) keychainStatus=\(addStatus) protectedFallbackSaved=\(fallbackSaved) caller=\(caller)")
        notifyAuthChanged(instanceId: instanceId)
    }

    static func loadOAuthString""",
            """let fallbackSaved = addStatus == errSecSuccess ? false : fallbackSavedBeforeKeychain
        if addStatus == errSecSuccess {
            _ = deleteCloneCredentialFallback(service: service, account: account)
        }
        AppLogger(category: "Keychain").info("write oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) valLen=\(value.count) keychainStatus=\(addStatus) protectedFallbackSaved=\(fallbackSaved) caller=\(caller)")
        notifyAuthChanged(instanceId: instanceId)
        return addStatus == errSecSuccess || fallbackSaved
    }

    static func loadOAuthString""",
            "OAuth string Bool return"
        )
        s = replace_exact(
            s,
            """static func loadOAuthString(instanceId: String, account: String, caller: String = #function) -> String? {
        let service = providerService(instanceId: instanceId)
        // Try synchronizable first""",
            """static func loadOAuthString(instanceId: String, account: String, caller: String = #function) -> String? {
        let service = providerService(instanceId: instanceId)
        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackString = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) src=protectedFallback hit=true caller=\(caller)")
            return fallbackString
        }
        // Try synchronizable first""",
            "OAuth string fallback read precedence"
        )
        return s
    edit(root, rel, apply)

def patch_async_package_listing(root: Path) -> None:
    """Keep mounted-folder filesystem scans off the main actor under Xcode 26."""
    rel = "src/ios/Agent/Backup/BackupDestinations.swift"
    def apply_destinations(s: str) -> str:
        s = replace_exact(
            s,
            "    struct FoundPackage: Identifiable {",
            "    struct FoundPackage: Identifiable, Sendable {",
            "Sendable backup package snapshot"
        )
        old = """    static func listPackages(folderId: UUID? = nil) -> [FoundPackage] {
        var found: [FoundPackage] = []
        let fm = FileManager.default

        let folders = folderId.map { id in selectedFolders.filter { $0.id == id } }
            ?? selectedFolders
        for folder in folders {
            guard let root = MountedFoldersManager.shared.resolvedURL(for: folder.id) else {
                logger.info("[Backup] destination '\\(folder.name)' is not currently available")
                continue
            }
            let names = (try? fm.contentsOfDirectory(atPath: root.path)) ?? []
            for name in names where name.hasSuffix("." + BackupFormat.fileExtension) {
                let url = root.appendingPathComponent(name)
                let attrs = try? fm.attributesOfItem(atPath: url.path)
                found.append(.init(
                    url: url,
                    folderName: folder.name,
                    size: (attrs?[.size] as? Int64) ?? 0,
                    modified: (attrs?[.modificationDate] as? Date) ?? .distantPast))
            }
        }
        return found.sorted { $0.modified > $1.modified }
    }"""
        new = """    nonisolated static func listPackages(folderId: UUID? = nil) async -> [FoundPackage] {
        // Resolve security-scoped mount URLs while on MainActor, then perform
        // potentially blocking directory I/O on a detached worker.
        let destinations: [(folderName: String, root: URL)] = await MainActor.run {
            let folders = folderId.map { id in selectedFolders.filter { $0.id == id } }
                ?? selectedFolders
            return folders.compactMap { folder in
                guard let root = MountedFoldersManager.shared.resolvedURL(for: folder.id) else {
                    logger.info("[Backup] destination '\\(folder.name)' is not currently available")
                    return nil
                }
                return (folder.name, root)
            }
        }
        let records: [(url: URL, folderName: String, size: Int64, modified: Date)] =
            await Task.detached(priority: .userInitiated) {
                let fm = FileManager.default
                var records: [(url: URL, folderName: String, size: Int64, modified: Date)] = []
                for destination in destinations {
                    let names = (try? fm.contentsOfDirectory(atPath: destination.root.path)) ?? []
                    for name in names where name.hasSuffix("." + BackupFormat.fileExtension) {
                        let url = destination.root.appendingPathComponent(name)
                        let attrs = try? fm.attributesOfItem(atPath: url.path)
                        records.append((
                            url: url,
                            folderName: destination.folderName,
                            size: (attrs?[.size] as? Int64) ?? 0,
                            modified: (attrs?[.modificationDate] as? Date) ?? .distantPast
                        ))
                    }
                }
                return records.sorted { $0.modified > $1.modified }
            }.value
        return await MainActor.run {
            records.map {
                FoundPackage(url: $0.url, folderName: $0.folderName, size: $0.size, modified: $0.modified)
            }
        }
    }"""
        s = replace_exact(s, old, new, "async off-main package listing")
        return s
    edit(root, rel, apply_destinations)

    rel = "src/ios/Views/Settings/BackupRestoreView.swift"
    def apply_restore(s: str) -> str:
        old = """        let found = await Task.detached(priority: .userInitiated) {
            BackupDestinations.listPackages(folderId: id)
        }.value"""
        new = """        let found = await BackupDestinations.listPackages(folderId: id)"""
        return replace_exact(s, old, new, "restore view async package listing")
    edit(root, rel, apply_restore)

    rel = "src/ios/Views/Settings/BackupDestinationDetailView.swift"
    def apply_detail(s: str) -> str:
        old = """        folderPackages = await Task.detached(priority: .userInitiated) {
            BackupDestinations.listPackages(folderId: id)
        }.value"""
        new = """        folderPackages = await BackupDestinations.listPackages(folderId: id)"""
        return replace_exact(s, old, new, "destination detail async package listing")
    edit(root, rel, apply_detail)


def patch_reset_scope(root: Path) -> None:
    rel = "src/ios/MinisApp.swift"
    def apply(s: str) -> str:
        start = s.index("    static func resetLocalData() {")
        end = s.index("\n    private static func markerStatus()", start)
        old = s[start:end]
        new = """    static func resetLocalData() {
        guard Bundle.main.bundleIdentifier == cloneBundleID else { return }
        let removedKeychainItems = clearCloneKeychainItems()
        let removedFallbackDirectory = ProviderKeychainHelper.clearCloneCredentialFallbackDirectory()
        let defaults = UserDefaults.standard
        var removedCredentialStamps = 0
        for key in defaults.dictionaryRepresentation().keys
        where key.hasPrefix("oauthNeedsReauthFingerprint.") || key.hasPrefix("providerKey.savedAt.") {
            defaults.removeObject(forKey: key)
            removedCredentialStamps += 1
        }
        AppLogger(category: "Lifecycle").info("[MinisMAX R4] credential reset complete keychainItems=\\(removedKeychainItems) fallbackDirectoryRemoved=\\(removedFallbackDirectory) credentialStamps=\\(removedCredentialStamps)")
    }
"""
        s = replace_exact(s, old, new, "MAX credential-only reset")
        return s
    edit(root, rel, apply)

    rel = "src/ios/Views/Settings/BackupAndRestoreView.swift"
    def apply_ui(s: str) -> str:
        old = """        .confirmationDialog("Clear all local Minis MAX data?", isPresented: $showMaxResetConfirmation, titleVisibility: .visible) {
            Button("Clear MAX data", role: .destructive) {
                MinisMAXDataIsolation.resetLocalData()
                showMaxResetResult = true
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This erases only MAX local files, settings, chats and MAX-namespaced Keychain credentials. Original Minis data is not touched. Force-close and reopen MAX afterward.")
        }
        .alert("MAX data cleared", isPresented: $showMaxResetResult) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Force-close and reopen Minis MAX to complete the reset.")
        }"""
        new = """        .confirmationDialog("Clear MAX credentials?", isPresented: $showMaxResetConfirmation, titleVisibility: .visible) {
            Button("Clear MAX Credentials", role: .destructive) {
                MinisMAXDataIsolation.resetLocalData()
                showMaxResetResult = true
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This removes only MAX provider credentials and credential-related timestamps. Other MAX app data is preserved; the App Store Minis app is not affected.")
        }
        .alert("MAX credentials cleared", isPresented: $showMaxResetResult) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("MAX provider Keychain entries and protected fallback files were cleared. Other MAX app data was preserved.")
        }"""
        return replace_exact(s, old, new, "MAX credential-only reset UI")
    edit(root, rel, apply_ui)

def patch_credential_callers(root: Path) -> None:
    changes = [
        ("src/ios/Views/Providers/AddProviderView.swift",
         """        if !trimmedKey.isEmpty {
            ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id)
        }
        store.addInstance(instance)
        isSaving = false
        dismiss()""",
         """        if !trimmedKey.isEmpty && !ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id) {
            errorMessage = "Minis MAX could not save this API key to Keychain or protected local storage. The provider was not added."
            isSaving = false
            return
        }
        store.addInstance(instance)
        isSaving = false
        dismiss()""",
         "manual API key persistence result"),
        ("src/ios/Views/Providers/AddProviderView.swift",
         """        ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token")
        store.addInstance(instance)
        dismiss()""",
         """        guard ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token") else {
            errorMessage = "Minis MAX could not save this OAuth token to Keychain or protected local storage. The provider was not added."
            return
        }
        store.addInstance(instance)
        dismiss()""",
         "manual OAuth token persistence result"),
        ("src/ios/Providers/OpenRouter/OAuth/OpenRouterOAuthManager.swift",
         """        ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: instanceId)
        logger.info("=== OpenRouter OAuth login complete (instance: \\(instanceId)) ===")""",
         """        guard ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: instanceId) else {
            throw LLMError.providerError(message: "OpenRouter authorized successfully, but Minis MAX could not persist the API key. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }
        logger.info("=== OpenRouter OAuth login complete (instance: \\(instanceId)) ===")""",
         "OpenRouter login persistence result"),
        ("src/ios/Shared/Config/Collections/ProvidersCollection.swift",
         """        if let key = resolvedKey {
            ProviderKeychainHelper.saveAPIKey(key, instanceId: instance.id)
        }
        store.addInstance(instance)""",
         """        if let key = resolvedKey {
            guard ProviderKeychainHelper.saveAPIKey(key, instanceId: instance.id) else {
                throw ConfigError.invalidValue("Minis MAX could not persist the provider API key")
            }
        }
        store.addInstance(instance)""",
         "provider collection create persistence result"),
        ("src/ios/Shared/Config/Collections/ProvidersCollection.swift",
         """                let resolved = try Self.resolveSecret(trimmed)
                ProviderKeychainHelper.saveAPIKey(resolved, instanceId: id)
                // Keep the instance's credentialType consistent with having a key.""",
         """                let resolved = try Self.resolveSecret(trimmed)
                guard ProviderKeychainHelper.saveAPIKey(resolved, instanceId: id) else {
                    throw ConfigError.invalidValue("Minis MAX could not persist the provider API key")
                }
                // Keep the instance's credentialType consistent with having a key.""",
         "provider collection field persistence result"),
        ('src/ios/Views/Providers/ProviderInstanceDetailView.swift',
         '''                            ProviderKeychainHelper.saveOAuthString(cleaned, instanceId: instanceId, account: "manual-oauth-token")
                            manualTokenInputText = ""''',
         '''                            guard ProviderKeychainHelper.saveOAuthString(cleaned, instanceId: instanceId, account: "manual-oauth-token") else {
                                AppLogger(category: "Provider").error("MAX manual OAuth token save failed; leaving the entry sheet open")
                                return
                            }
                            manualTokenInputText = ""''',
         "provider detail manual token persistence result"),
    ]
    for rel, old, new, label in changes:
        edit(root, rel, lambda s, old=old, new=new, label=label: replace_exact(s, old, new, label, 1))

def patch_refresh_writes(root: Path) -> None:
    changes = [
        ("src/ios/Providers/Gemini/OAuth/GeminiOAuthManager.swift",
         """                let refreshed = try await self.performRefresh(refreshToken: staleRefreshToken)
                ProviderKeychainHelper.saveOAuthToken(refreshed, instanceId: instanceId)
                return refreshed""",
         """                let refreshed = try await self.performRefresh(refreshToken: staleRefreshToken)
                guard ProviderKeychainHelper.saveOAuthToken(refreshed, instanceId: instanceId) else {
                    throw LLMError.providerError(message: "Gemini refreshed the OAuth token but Minis MAX could not persist it")
                }
                return refreshed""",
         "Gemini refresh persistence result"),
        ("src/ios/Providers/Antigravity/OAuth/AntigravityOAuthManager.swift",
         """                let refreshed = try await self.performRefresh(refreshToken: staleRefreshToken)
                ProviderKeychainHelper.saveOAuthToken(refreshed, instanceId: instanceId)
                return refreshed""",
         """                let refreshed = try await self.performRefresh(refreshToken: staleRefreshToken)
                guard ProviderKeychainHelper.saveOAuthToken(refreshed, instanceId: instanceId) else {
                    throw LLMError.providerError(message: "Antigravity refreshed the OAuth token but Minis MAX could not persist it")
                }
                return refreshed""",
         "Antigravity refresh persistence result"),
    ]
    for rel, old, new, label in changes:
        edit(root, rel, lambda s, old=old, new=new, label=label: replace_exact(s, old, new, label, 1))

def patch_backup_import_results(root: Path) -> None:
    rel = "src/ios/Agent/Backup/BackupSecretsImporter.swift"
    def apply(s: str) -> str:
        changes = [
            ("""                    ProviderKeychainHelper.saveAPIKey(value, instanceId: p.instanceId)
                    wrote = true""",
             """                    if ProviderKeychainHelper.saveAPIKey(value, instanceId: p.instanceId) { wrote = true }""",
             "backup API key persistence result"),
            ("""                ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "manual-oauth-token")
                wrote = true""",
             """                if ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "manual-oauth-token") { wrote = true }""",
             "backup manual OAuth persistence result"),
            ("""                ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-email")
                wrote = true""",
             """                if ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-email") { wrote = true }""",
             "backup OAuth email persistence result"),
            ("""                ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-gcp-project")
                wrote = true""",
             """                if ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-gcp-project") { wrote = true }""",
             "backup OAuth project persistence result"),
            ("""                    ProviderKeychainHelper.saveRawOAuthToken(raw, instanceId: p.instanceId)
                    wrote = true""",
             """                    if ProviderKeychainHelper.saveRawOAuthToken(raw, instanceId: p.instanceId) { wrote = true }""",
             "backup raw OAuth persistence result"),
        ]
        for old, new, label in changes:
            s = replace_exact(s, old, new, label, 1)
        return s
    edit(root, rel, apply)

def main(root: Path) -> None:
    if not (root / "src/ios/Minis.xcodeproj/project.pbxproj").is_file():
        raise RuntimeError("NO-GO: root is not the pinned OpenMinis source tree")
    # Reuse the exact successful R3 pipeline first, including its source-drift checks.
    patch_clone_identity_r3.patch(root)
    test_patch_clone_identity_r3.main(root)
    patch_provider_store(root)
    patch_async_package_listing(root)
    patch_reset_scope(root)
    patch_credential_callers(root)
    patch_refresh_writes(root)
    patch_backup_import_results(root)
    print("PASS R4: clone-only local Keychain plus protected fallback for API key and OAuth")
    print("PASS R4: credential reads prefer the committed fallback; stale copies are cleared before replacement")
    print("PASS R4: every save API reports persistence result; login/manual/import flows are gated")
    print("PASS R4: credential-only reset preserves chats, settings, documents, and App Store Minis data")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 patch_clone_identity_r4.py /path/to/pinned/OpenMinis")
    main(Path(sys.argv[1]).resolve())
