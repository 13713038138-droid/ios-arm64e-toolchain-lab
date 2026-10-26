#!/usr/bin/env python3
"""IPS 2026-10-22 EXC_BREAKPOINT/SIGTRAP at minisAppGroupRoot:
surgical App Group fallback and isolated test clone migration safety.
Only apply to the pinned OpenMinis source; fail closed on drift.
"""
from pathlib import Path
import os
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_ips_sigtrap.py <OpenMinis repo>")
repo = Path(sys.argv[1]).resolve()
bundle_id = os.environ.get("MINIS_MAX_BUNDLE_ID", "com.openminis.devultramax")
if bundle_id not in ("com.openminis.devultramax", "com.openminis.devultramax.r5", "com.openminis.devultramax.r54", "com.openminis.devultramax.r55", "com.openminis.devultramax.r56", "com.openminis.devultramax.r57", "com.openminis.devultramax.r58", "com.openminis.devultramax.r59", "com.openminis.devultramax.r60"):
    raise SystemExit("NO-GO: unsupported isolated test bundle identity")
src = repo / "src/ios"
budget = src / "Agent/Chat/AIChatViewModel+RequestBudget.swift"
app = src / "MinisApp.swift"
extension = src / "FileProvider/FileProviderExtension.swift"
assert all(p.is_file() for p in [budget, app, extension]), "NO-GO: unexpected source tree"

def replace_once(src_text, old, new, label):
    # The isolated R5 clone changes the bundle ID; keep patch signatures aligned
    # without double-appending a version suffix to already-updated source.
    old = re.sub(r"com\.openminis\.devultramax(?!\.r[0-9]+)", lambda _: bundle_id, old)
    new = re.sub(r"com\.openminis\.devultramax(?!\.r[0-9]+)", lambda _: bundle_id, new)
    n = src_text.count(old)
    if n != 1:
        raise RuntimeError(f"NO-GO {label}: expected one known source site, got {n}")
    return src_text.replace(old, new, 1)

# A separate test identity may never request the original App Store containers.
old_group = "group.com.openminis.app"
new_group = "group." + bundle_id
old_icloud = "iCloud.com.openminis.app"
new_icloud = "iCloud." + bundle_id
old_fp = "com.openminis.app.files"
new_fp = bundle_id + ".files"
changed = []
for p in sorted(src.rglob("*")):
    if not p.is_file() or p.suffix not in (".swift", ".entitlements", ".plist"):
        continue
    s = p.read_text(encoding="utf-8")
    t = s.replace(old_group, new_group).replace(old_icloud, new_icloud)
    t = t.replace(old_fp, new_fp).replace("com.openminis.app", bundle_id)
    if t != s:
        p.write_text(t, encoding="utf-8")
        changed.append(p.relative_to(src).as_posix())
if len(changed) < 10:
    raise RuntimeError("NO-GO: expected all cloned entitlements and source references")

p = budget
s = p.read_text(encoding="utf-8")
s = replace_once(s,
'''    nonisolated static var minisAppGroupRoot: URL {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        )!.appendingPathComponent("MinisFileProvider", isDirectory: true)
    }''',
'''    // IPS 2C490985-8E4F-47D8-AC93-13D7CD186ACB:
    // Non-AppStore ad-hoc signatures may not receive the App Group entitlement.
    // Use ONLY this clone's application container when it is unavailable.
    // Never force-unwrap the original App Store App Group.
    nonisolated static var minisIsolatedContainerBase: URL {
        if let shared = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        ) {
            return shared
        }
        let local = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
            .appendingPathComponent("Library/MinisDevUltraIsolated", isDirectory: true)
        try? FileManager.default.createDirectory(
            at: local, withIntermediateDirectories: true
        )
        return local
    }

    nonisolated static var minisAppGroupRoot: URL {
        minisIsolatedContainerBase.appendingPathComponent(
            "MinisFileProvider", isDirectory: true
        )
    }''', "main app root getter")
s = replace_once(s,
'''        let url = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        )!.appendingPathComponent("MinisConfig", isDirectory: true)''',
'''        let url = minisIsolatedContainerBase.appendingPathComponent(
            "MinisConfig", isDirectory: true
        )''', "main app config getter")
p.write_text(s, encoding="utf-8")

p = app
s = p.read_text(encoding="utf-8")
s = replace_once(s,
'''    private static func registerFileProviderDomain() {
        logAppUpdateMarkerForFPTrace()''',
'''    private static func registerFileProviderDomain() {
        // The ad-hoc test clone lacks a shared FileProvider entitlement on
        // some TrollStore installs. Do not register a broken domain.
        guard FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        ) != nil else {
            lifecycleLog.warning("[IsolatedTest] FileProvider registration skipped: no cloned App Group entitlement")
            return
        }
        logAppUpdateMarkerForFPTrace()''', "FileProvider registration guard")
s = replace_once(s,
f'''        let container = fm.containerURL(forSecurityApplicationGroupIdentifier: "{new_group}")!''',
'''        guard let container = fm.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        ) else {
            lifecycleLog.info("[IsolatedTest] no App Group; skipping App Group migration")
            return
        }''', "legacy shared migration guard")
p.write_text(s, encoding="utf-8")

p = extension
s = p.read_text(encoding="utf-8")
s = replace_once(s,
f'''        let container = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "{new_group}"
        )!
        let url = container.appendingPathComponent("MinisFileProvider", isDirectory: true)''',
f'''        let shared = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "{new_group}"
        )
        let root = shared ?? URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
            .appendingPathComponent("Library/MinisDevUltraExtensionIsolated", isDirectory: true)
        let url = root.appendingPathComponent("MinisFileProvider", isDirectory: true)''', "FileProvider extension no-entitlement fallback")
p.write_text(s, encoding="utf-8")

# MAX R4 credential persistence: local Keychain first, protected-file fallback only for the clone.
p = src / "Providers/ProviderConfigStore.swift"
ps = p.read_text(encoding="utf-8")
if "import CryptoKit" not in ps or "import Security" not in ps:
    raise RuntimeError("NO-GO: expected CryptoKit and Security imports")
if "com.openminis.app.provider." in ps:
    raise RuntimeError("NO-GO: original provider Keychain namespace remains")

helper_anchor = 'enum ProviderKeychainHelper {\n    private static let account = "api-key"'
helper = r'''enum ProviderKeychainHelper {
    private static let account = "api-key"

    // Only the isolated MAX clone may use this protected fallback.
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
                // Enforce protection even when the directory already existed.
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
        // Hash the lookup key so service/account identifiers are not exposed in filenames.
        let key = Data("\(service)|\(account)".utf8)
        let name = SHA256.hash(data: key).map { String(format: "%02x", $0) }.joined()
        return directory.appendingPathComponent(name + ".credential", isDirectory: false)
    }

    private static func writeCloneCredentialFallback(_ data: Data, service: String, account: String) -> Bool {
        guard let url = cloneCredentialFallbackURL(service: service, account: account, createDirectory: true),
              let directory = cloneCredentialFallbackDirectory(createIfMissing: false) else { return false }
        // Prepare and protect a sibling temp file before replacing the committed credential.
        // A failed write must never delete the previous valid credential.
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
            // Only the uncommitted temporary file may be removed; preserve the old credential.
            try? FileManager.default.removeItem(at: temporaryURL)
            AppLogger(category: "Keychain").error("MAX protected fallback credential write failed: \(error.localizedDescription)")
            return false
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
        // Any result except "definitely absent" might represent the last valid credential.
        let keychainMayHaveCredential = keychainStatus != errSecItemNotFound
        let saved = writeCloneCredentialFallback(data, service: service, account: account)
        return (saved || (!fallbackWasPresent && !keychainMayHaveCredential), saved)
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

    @discardableResult
    private static func deleteCloneCredentialFallback(service: String, account: String) -> Bool {
        // For the App Store identity, file fallback is disabled and not applicable.
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
    }'''
ps = replace_once(ps, helper_anchor, helper, "MAX protected fallback helpers")

sync_write = '        addQuery[kSecAttrSynchronizable as String] = true\n'
if ps.count(sync_write) != 4:
    raise RuntimeError(f"NO-GO local-only Keychain policy: expected 4 sync-write attributes, found {ps.count(sync_write)}")
ps = ps.replace(sync_write, "")

# API key: stage a protected recovery copy before replacing Keychain; remove it only after success.
ps = replace_once(ps,
'''        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        // Stamp the local save time for iCloud LWW conflict resolution.
        stampAPIKeySavedAt(Date(), instanceId: instanceId)
        AppLogger(category: "Keychain").info("write apiKey instanceId=\(instanceId.prefix(8)) keyLen=\(key.count) addStatus=\(addStatus) caller=\(caller)")
        // Refresh credential-derived UI (provider list "configured" dot, etc).
        notifyAuthChanged(instanceId: instanceId)''',
'''        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = fallbackSavedBeforeKeychain
        if addStatus == errSecSuccess && fallbackSavedBeforeKeychain {
            _ = deleteCloneCredentialFallback(service: service, account: account)
        }
        AppLogger(category: "Keychain").info("write apiKey instanceId=\(instanceId.prefix(8)) keyLen=\(key.count) keychainStatus=\(addStatus) protectedFallbackSaved=\(fallbackSaved) caller=\(caller)")
        if addStatus == errSecSuccess || fallbackSaved {
            stampAPIKeySavedAt(Date(), instanceId: instanceId)
        } else {
            AppLogger(category: "Keychain").error("write apiKey FAILED instanceId=\(instanceId.prefix(8)) status=\(addStatus) protectedFallbackSaved=false caller=\(caller)")
        }
        notifyAuthChanged(instanceId: instanceId)''',
"API key protected fallback write")
ps = replace_once(ps,
'''            return s
        }
        // Fallback to legacy non-sync entry''',
'''            if let s { return s }
        }
        // Fallback to legacy non-sync entry''',
"API key continue after invalid Keychain bytes")
ps = replace_once(ps,
'''        let legacyStatus = SecItemCopyMatching(legacyQuery as CFDictionary, &result)
        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) caller=\(caller)")
            return nil
        }
        let s = String(data: data, encoding: .utf8)
        AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) src=legacy hit=\(s != nil) keyLen=\(s?.count ?? 0) syncStatus=\(syncStatus) caller=\(caller)")
        return s''',
'''        let legacyStatus = SecItemCopyMatching(legacyQuery as CFDictionary, &result)
        if legacyStatus == errSecSuccess, let data = result as? Data,
           let value = String(data: data, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) src=legacy hit=true keyLen=\(value.count) syncStatus=\(syncStatus) caller=\(caller)")
            return value
        }
        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackKey = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true keyLen=\(fallbackKey.count) caller=\(caller)")
            return fallbackKey
        }
        AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallback=false caller=\(caller)")
        return nil''',
"API key protected fallback read")
ps = replace_once(ps,
'''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        // Clear the LWW stamp so any subsequent import (e.g. rebinding from another
        // device) isn't blocked by a stale "local is newer" comparison.''',
'''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        let fallbackRemoved = deleteCloneCredentialFallback(service: service, account: account)
        // Clear the LWW stamp so any subsequent import (e.g. rebinding from another
        // device) isn't blocked by a stale "local is newer" comparison.''',
"API key protected fallback delete")
ps = replace_once(ps,
'''delete apiKey instanceId=\(instanceId.prefix(8)) legacyStatus=\(s1) syncStatus=\(s2) caller=\(caller)''',
'''delete apiKey instanceId=\(instanceId.prefix(8)) legacyStatus=\(s1) syncStatus=\(s2) protectedFallbackRemoved=\(fallbackRemoved) caller=\(caller)''',
"API key delete logging")

# Raw OAuth token: share the typed-token fallback and stage it before destructive Keychain changes.
ps = replace_once(ps,
'''        let status = SecItemAdd(addQuery as CFDictionary, nil)
        if status != errSecSuccess {
            AppLogger(category: "Keychain").warning("write rawOAuthToken instanceId=\(instanceId.prefix(8)) status=\(status)")
        }
        clearOAuthNeedsReauth(instanceId: instanceId)''',
'''        let status = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = fallbackSavedBeforeKeychain
        if status == errSecSuccess && fallbackSavedBeforeKeychain {
            _ = deleteCloneCredentialFallback(service: service, account: acct)
        }
        AppLogger(category: "Keychain").info("write rawOAuthToken instanceId=\(instanceId.prefix(8)) keychainStatus=\(status) protectedFallbackSaved=\(fallbackSaved)")
        if status == errSecSuccess || fallbackSaved {
            clearOAuthNeedsReauth(instanceId: instanceId)
        } else {
            AppLogger(category: "Keychain").error("write rawOAuthToken FAILED instanceId=\(instanceId.prefix(8)) status=\(status) protectedFallbackSaved=false")
        }
        notifyAuthChanged(instanceId: instanceId)''',
"raw OAuth protected fallback write")
ps = replace_once(ps,
'''        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data''',
'''        var result: AnyObject?
        let keychainStatus = SecItemCopyMatching(query as CFDictionary, &result)
        if keychainStatus == errSecSuccess, let data = result as? Data { return data }
        if let fallbackData = readCloneCredentialFallback(service: service, account: "oauth-token") {
            AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true keychainStatus=\(keychainStatus)")
            return fallbackData
        }
        AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) hit=false keychainStatus=\(keychainStatus) protectedFallback=false")
        return nil''',
"raw OAuth protected fallback read")

# Typed OAuth: stage a protected recovery copy before destructive Keychain changes.
ps = replace_once(ps,
'''static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) {''',
'''@discardableResult
    static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) -> Bool {''',
"typed OAuth save result")
ps = replace_once(ps,
'''        guard let data = try? JSONEncoder().encode(token) else {
            AppLogger(category: "Keychain").warning("write oauthToken instanceId=\(instanceId.prefix(8)) ENCODE FAILED caller=\(caller)")
            return
        }''',
'''        guard let data = try? JSONEncoder().encode(token) else {
            AppLogger(category: "Keychain").error("write oauthToken instanceId=\(instanceId.prefix(8)) ENCODE FAILED caller=\(caller)")
            return false
        }''',
"typed OAuth encode failure")
ps = replace_once(ps,
'''        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        AppLogger(category: "Keychain").info("write oauthToken instanceId=\(instanceId.prefix(8)) blobLen=\(data.count) addStatus=\(addStatus) caller=\(caller)")
        clearOAuthNeedsReauth(instanceId: instanceId)
        notifyAuthChanged(instanceId: instanceId)''',
'''        let keychainStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = fallbackSavedBeforeKeychain
        if keychainStatus == errSecSuccess && fallbackSavedBeforeKeychain {
            _ = deleteCloneCredentialFallback(service: service, account: acct)
        }
        AppLogger(category: "Keychain").info("write oauthToken instanceId=\(instanceId.prefix(8)) blobLen=\(data.count) keychainStatus=\(keychainStatus) protectedFallbackSaved=\(fallbackSaved) caller=\(caller)")
        guard keychainStatus == errSecSuccess || fallbackSaved else {
            AppLogger(category: "Keychain").error("write oauthToken FAILED instanceId=\(instanceId.prefix(8)) status=\(keychainStatus) protectedFallbackSaved=false caller=\(caller)")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        clearOAuthNeedsReauth(instanceId: instanceId)
        notifyAuthChanged(instanceId: instanceId)
        return true''',
"typed OAuth protected fallback write")
ps = replace_once(ps,
'''            return decoded
        }
        // Fallback to legacy''',
'''            if let decoded { return decoded }
        }
        // Fallback to legacy''',
"typed OAuth continue after decode failure")
ps = replace_once(ps,
'''        let legacyStatus = SecItemCopyMatching(query as CFDictionary, &result)
        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) caller=\(caller)")
            return nil
        }
        let decoded = try? JSONDecoder().decode(type, from: data)
        AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) src=legacy hit=true decoded=\(decoded != nil) syncStatus=\(syncStatus) caller=\(caller)")
        return decoded''',
'''        let legacyStatus = SecItemCopyMatching(query as CFDictionary, &result)
        if legacyStatus == errSecSuccess, let data = result as? Data,
           let decoded = try? JSONDecoder().decode(type, from: data) {
            AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) src=legacy hit=true decoded=true syncStatus=\(syncStatus) caller=\(caller)")
            return decoded
        }
        if let fallbackData = readCloneCredentialFallback(service: service, account: acct) {
            let fallbackToken = try? JSONDecoder().decode(type, from: fallbackData)
            AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=\(fallbackToken != nil) legacyStatus=\(legacyStatus) caller=\(caller)")
            return fallbackToken
        }
        AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallback=false caller=\(caller)")
        return nil''',
"typed OAuth protected fallback read")
ps = replace_once(ps,
'''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        AppLogger(category: "Keychain").info("delete oauthToken instanceId=\(instanceId.prefix(8)) legacyStatus=\(s1) syncStatus=\(s2) caller=\(caller)")''',
'''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        let fallbackRemoved = deleteCloneCredentialFallback(service: service, account: acct)
        AppLogger(category: "Keychain").info("delete oauthToken instanceId=\(instanceId.prefix(8)) legacyStatus=\(s1) syncStatus=\(s2) protectedFallbackRemoved=\(fallbackRemoved) caller=\(caller)")''',
"typed OAuth protected fallback delete")

# OAuth metadata strings use the same staged fallback transaction.
ps = replace_once(ps,
'''        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        AppLogger(category: "Keychain").info("write oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) valLen=\(value.count) addStatus=\(addStatus) caller=\(caller)")
        notifyAuthChanged(instanceId: instanceId)''',
'''        let keychainStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let fallbackSaved = fallbackSavedBeforeKeychain
        if keychainStatus == errSecSuccess && fallbackSavedBeforeKeychain {
            _ = deleteCloneCredentialFallback(service: service, account: account)
        }
        AppLogger(category: "Keychain").info("write oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) valLen=\(value.count) keychainStatus=\(keychainStatus) protectedFallbackSaved=\(fallbackSaved) caller=\(caller)")
        if keychainStatus != errSecSuccess && !fallbackSaved {
            AppLogger(category: "Keychain").error("write oauthString FAILED instanceId=\(instanceId.prefix(8)) acct=\(account) status=\(keychainStatus) protectedFallbackSaved=false caller=\(caller)")
        }
        notifyAuthChanged(instanceId: instanceId)''',
"OAuth string protected fallback write")
ps = replace_once(ps,
'''            return s
        }
        // Fallback to legacy''',
'''            if let s { return s }
        }
        // Fallback to legacy''',
"OAuth string continue after invalid Keychain bytes")
ps = replace_once(ps,
'''        let legacyStatus = SecItemCopyMatching(query as CFDictionary, &result)
        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) caller=\(caller)")
            return nil
        }
        let s = String(data: data, encoding: .utf8)
        AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) src=legacy hit=\(s != nil) valLen=\(s?.count ?? 0) syncStatus=\(syncStatus) caller=\(caller)")
        return s''',
'''        let legacyStatus = SecItemCopyMatching(query as CFDictionary, &result)
        if legacyStatus == errSecSuccess, let data = result as? Data,
           let value = String(data: data, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) src=legacy hit=true valLen=\(value.count) syncStatus=\(syncStatus) caller=\(caller)")
            return value
        }
        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackString = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) src=protectedFallback hit=true caller=\(caller)")
            return fallbackString
        }
        AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallback=false caller=\(caller)")
        return nil''',
"OAuth string protected fallback read")
ps = replace_once(ps,
'''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        AppLogger(category: "Keychain").info("delete oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) legacyStatus=\(s1) syncStatus=\(s2) caller=\(caller)")''',
'''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        let fallbackRemoved = deleteCloneCredentialFallback(service: service, account: account)
        AppLogger(category: "Keychain").info("delete oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) legacyStatus=\(s1) syncStatus=\(s2) protectedFallbackRemoved=\(fallbackRemoved) caller=\(caller)")''',
"OAuth string protected fallback delete")

if 'addQuery[kSecAttrSynchronizable as String] = true' in ps:
    raise RuntimeError("NO-GO: MAX credential writes still request Keychain sync")
if 'addQuery[kSecAttrSynchronizable as String] != nil' in ps:
    raise RuntimeError("NO-GO: credential fallback still depends on a synchronization attribute")
if 'fallbackAttempted = true' in ps or 'localQuery[kSecValueData as String]' in ps:
    raise RuntimeError("NO-GO: obsolete sync-dependent local Keychain fallback remains")

# Remove any prior file fallback before replacing the Keychain item. If removal
# fails, abort the write rather than leave an older token eligible for fallback.
ps = replace_once(ps,
'''static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        // Delete both legacy (non-sync) and synchronizable entries''',
'''@discardableResult
    static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) -> Bool {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let fallbackStage = stageCloneCredentialFallback(Data(key.utf8), service: service, account: account)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write apiKey aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8))")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        // Delete both legacy (non-sync) and synchronizable entries''',
"API key stale fallback preclear")
ps = replace_once(ps,
'''static func saveRawOAuthToken(_ data: Data, instanceId: String) {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let acct = "oauth-token"
        let deleteQuery: [String: Any] = [''',
'''@discardableResult
    static func saveRawOAuthToken(_ data: Data, instanceId: String) -> Bool {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let acct = "oauth-token"
        let fallbackStage = stageCloneCredentialFallback(data, service: service, account: acct)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write rawOAuthToken aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8))")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        let deleteQuery: [String: Any] = [''',
"raw OAuth stale fallback preclear")
ps = replace_once(ps,
'''        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let acct = "oauth-token"
        let deleteQuery: [String: Any] = [''',
'''        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let acct = "oauth-token"
        let fallbackStage = stageCloneCredentialFallback(data, service: service, account: acct)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write oauthToken aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8))")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        let deleteQuery: [String: Any] = [''',
"typed OAuth stale fallback preclear")
ps = replace_once(ps,
'''static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) {''',
'''@discardableResult
    static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {''',
"OAuth string Bool result")
ps = replace_once(ps,
'''        notifyAuthChanged(instanceId: instanceId)
    }

    static func loadOAuthString(instanceId: String, account: String, caller: String = #function) -> String? {''',
'''        notifyAuthChanged(instanceId: instanceId)
        return keychainStatus == errSecSuccess || fallbackSaved
    }

    static func loadOAuthString(instanceId: String, account: String, caller: String = #function) -> String? {''',
"OAuth string Bool return")

ps = replace_once(ps,
'''@discardableResult
    static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let deleteQuery: [String: Any] = [''',
'''@discardableResult
    static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let fallbackStage = stageCloneCredentialFallback(Data(value.utf8), service: service, account: account)
        guard fallbackStage.safeToProceed else {
            AppLogger(category: "Keychain").error("write oauthString aborted: cannot safely stage existing credential instanceId=\(instanceId.prefix(8)) acct=\(account)")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        let fallbackSavedBeforeKeychain = fallbackStage.saved
        let deleteQuery: [String: Any] = [''',
"OAuth string stale fallback preclear")
ps = replace_once(ps,
'''        notifyAuthChanged(instanceId: instanceId)
    }

    static func loadAPIKey(instanceId: String, caller: String = #function) -> String? {''',
'''        notifyAuthChanged(instanceId: instanceId)
        return addStatus == errSecSuccess || fallbackSaved
    }

    static func loadAPIKey(instanceId: String, caller: String = #function) -> String? {''',
"API key Bool result")
ps = replace_once(ps,
'''        notifyAuthChanged(instanceId: instanceId)
    }

    static func loadRawOAuthToken(instanceId: String) -> Data? {''',
'''        notifyAuthChanged(instanceId: instanceId)
        return status == errSecSuccess || fallbackSaved
    }

    static func loadRawOAuthToken(instanceId: String) -> Data? {''',
"raw OAuth Bool result")


# A fallback file exists only after a prior Keychain write failed. Treat that
# copy as the current committed credential until a later successful write clears
# it; otherwise an unreadable/stale Keychain item could shadow the new token.
ps = replace_once(ps,
'''static func loadAPIKey(instanceId: String, caller: String = #function) -> String? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        // Try synchronizable first, then fallback to legacy''',
'''static func loadAPIKey(instanceId: String, caller: String = #function) -> String? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackKey = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true keyLen=\(fallbackKey.count) caller=\(caller)")
            return fallbackKey
        }
        // Try synchronizable first, then fallback to legacy''',
"API key committed fallback read precedence")
ps = replace_once(ps,
'''        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackKey = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true keyLen=\(fallbackKey.count) caller=\(caller)")
            return fallbackKey
        }
        AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallback=false caller=\(caller)")''',
'''        AppLogger(category: "Keychain").info("read apiKey instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallbackHit=false caller=\(caller)")''',
"API key remove late fallback")
ps = replace_once(ps,
'''static func loadRawOAuthToken(instanceId: String) -> Data? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        var query: [String: Any] = [''',
'''static func loadRawOAuthToken(instanceId: String) -> Data? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        if let fallbackData = readCloneCredentialFallback(service: service, account: "oauth-token") {
            AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true")
            return fallbackData
        }
        var query: [String: Any] = [''',
"raw OAuth committed fallback read precedence")
ps = replace_once(ps,
'''        let keychainStatus = SecItemCopyMatching(query as CFDictionary, &result)
        if keychainStatus == errSecSuccess, let data = result as? Data { return data }
        if let fallbackData = readCloneCredentialFallback(service: service, account: "oauth-token") {
            AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true keychainStatus=\(keychainStatus)")
            return fallbackData
        }
        AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) hit=false keychainStatus=\(keychainStatus) protectedFallback=false")''',
'''        let keychainStatus = SecItemCopyMatching(query as CFDictionary, &result)
        if keychainStatus == errSecSuccess, let data = result as? Data { return data }
        AppLogger(category: "Keychain").info("read rawOAuthToken instanceId=\(instanceId.prefix(8)) hit=false keychainStatus=\(keychainStatus) protectedFallbackHit=false")''',
"raw OAuth remove late fallback")
ps = replace_once(ps,
'''static func loadOAuthToken<T: Codable>(instanceId: String, as type: T.Type, caller: String = #function) -> T? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let acct = "oauth-token"
        // Try synchronizable first''',
'''static func loadOAuthToken<T: Codable>(instanceId: String, as type: T.Type, caller: String = #function) -> T? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        let acct = "oauth-token"
        if let fallbackData = readCloneCredentialFallback(service: service, account: acct) {
            if let fallbackToken = try? JSONDecoder().decode(type, from: fallbackData) {
                AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=true caller=\(caller)")
                return fallbackToken
            }
            AppLogger(category: "Keychain").error("read oauthToken instanceId=\(instanceId.prefix(8)) protected fallback UNDECODABLE as \(type); continuing to Keychain")
        }
        // Try synchronizable first''',
"typed OAuth committed fallback read precedence")
ps = replace_once(ps,
'''        if let fallbackData = readCloneCredentialFallback(service: service, account: acct) {
            let fallbackToken = try? JSONDecoder().decode(type, from: fallbackData)
            AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) src=protectedFallback hit=\(fallbackToken != nil) legacyStatus=\(legacyStatus) caller=\(caller)")
            return fallbackToken
        }
        AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallback=false caller=\(caller)")''',
'''        AppLogger(category: "Keychain").info("read oauthToken instanceId=\(instanceId.prefix(8)) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallbackHit=false caller=\(caller)")''',
"typed OAuth remove late fallback")
ps = replace_once(ps,
'''static func loadOAuthString(instanceId: String, account: String, caller: String = #function) -> String? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        // Try synchronizable first''',
'''static func loadOAuthString(instanceId: String, account: String, caller: String = #function) -> String? {
        let service = "com.openminis.devultramax.provider.\(instanceId)"
        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackString = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) src=protectedFallback hit=true caller=\(caller)")
            return fallbackString
        }
        // Try synchronizable first''',
"OAuth string committed fallback read precedence")
ps = replace_once(ps,
'''        if let fallbackData = readCloneCredentialFallback(service: service, account: account),
           let fallbackString = String(data: fallbackData, encoding: .utf8) {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) src=protectedFallback hit=true caller=\(caller)")
            return fallbackString
        }
        AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallback=false caller=\(caller)")''',
'''        AppLogger(category: "Keychain").info("read oauthString instanceId=\(instanceId.prefix(8)) acct=\(account) hit=false syncStatus=\(syncStatus) legacyStatus=\(legacyStatus) protectedFallbackHit=false caller=\(caller)")''',
"OAuth string remove late fallback")

p.write_text(ps, encoding="utf-8")

# Gate OAuth login completion on verified persistence.
changes = [
    ("Providers/Anthropic/OAuth/ClaudeOAuthManager.swift",
     '''        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)
        logger.info("=== OAuth login complete (instance: \(instanceId)) ===")''',
     '''        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }
        logger.info("=== OAuth login complete (instance: \(instanceId)) ===")''',
     "Claude login persistence result"),
    ("Providers/OpenAI/OAuth/CodexOAuthManager.swift",
     '''        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)
        logger.info("=== Codex OAuth login complete (instance: \(instanceId)) ===")''',
     '''        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }
        logger.info("=== Codex OAuth login complete (instance: \(instanceId)) ===")''',
     "Codex login persistence result"),
    ("Providers/Gemini/OAuth/GeminiOAuthManager.swift",
     '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)''',
     '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }''',
     "Gemini login persistence result"),
    ("Providers/Antigravity/OAuth/AntigravityOAuthManager.swift",
     '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)''',
     '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }''',
     "Antigravity login persistence result"),
    ("Providers/Kimi/OAuth/KimiOAuthManager.swift",
     '''        ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId)
        logger.info("Kimi device login complete (instance: \(instanceId))")''',
     '''        guard ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }
        logger.info("Kimi device login complete (instance: \(instanceId))")''',
     "Kimi login persistence result"),
    ("Providers/Copilot/OAuth/CopilotOAuthManager.swift",
     '''                let storage = CopilotTokenStorage(githubToken: accessToken)
                ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId)
                logger.info("[Copilot] device flow complete for instance \(instanceId.prefix(8))")''',
     '''                let storage = CopilotTokenStorage(githubToken: accessToken)
                guard ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId) else {
                    throw LLMError.providerError(message: "GitHub authorized successfully, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
                }
                logger.info("[Copilot] device flow complete for instance \(instanceId.prefix(8))")''',
     "Copilot login persistence result"),
    ("Providers/xAI/OAuth/XAIOAuthManager.swift",
     '''        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)
        // isAuthenticated(instanceId:) is a plain Keychain read, not @Published —''',
     '''        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }
        // isAuthenticated(instanceId:) is a plain Keychain read, not @Published —''',
     "xAI login persistence result"),
    ("Providers/OpenRouter/OAuth/OpenRouterOAuthManager.swift",
     '''        ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: instanceId)
        logger.info("=== OpenRouter OAuth login complete (instance: \(instanceId)) ===")''',
     '''        guard ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: instanceId) else {
            throw LLMError.providerError(message: "OpenRouter authorized successfully, but Minis MAX could not persist the API key. Keychain and protected local fallback both failed; retry after checking the app's storage access.")
        }
        logger.info("=== OpenRouter OAuth login complete (instance: \(instanceId)) ===")''',
     "OpenRouter login persistence result"),
    ("Views/Providers/AddProviderView.swift",
     '''        if !trimmedKey.isEmpty {
            ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id)
        }
        store.addInstance(instance)
        isSaving = false
        dismiss()''',
     '''        if !trimmedKey.isEmpty && !ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id) {
            errorMessage = "Minis MAX could not save this API key to Keychain or protected local storage. The provider was not added."
            isSaving = false
            return
        }
        store.addInstance(instance)
        isSaving = false
        dismiss()''',
     "manual API key persistence result"),
    ("Views/Providers/AddProviderView.swift",
     '''        ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token")
        store.addInstance(instance)
        dismiss()''',
     '''        guard ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token") else {
            errorMessage = "Minis MAX could not save this OAuth token to Keychain or protected local storage. The provider was not added."
            return
        }
        store.addInstance(instance)
        dismiss()''',
     "manual OAuth token persistence result"),
    ("Agent/Backup/BackupSecretsImporter.swift",
     '''                    ProviderKeychainHelper.saveAPIKey(value, instanceId: p.instanceId)
                    wrote = true''',
     '''                    if ProviderKeychainHelper.saveAPIKey(value, instanceId: p.instanceId) { wrote = true }''',
     "backup API key persistence result"),
    ("Agent/Backup/BackupSecretsImporter.swift",
     '''                ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "manual-oauth-token")
                wrote = true''',
     '''                if ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "manual-oauth-token") { wrote = true }''',
     "backup manual OAuth persistence result"),
    ("Agent/Backup/BackupSecretsImporter.swift",
     '''                ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-email")
                wrote = true''',
     '''                if ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-email") { wrote = true }''',
     "backup OAuth email persistence result"),
    ("Agent/Backup/BackupSecretsImporter.swift",
     '''                ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-gcp-project")
                wrote = true''',
     '''                if ProviderKeychainHelper.saveOAuthString(
                    value, instanceId: p.instanceId, account: "oauth-gcp-project") { wrote = true }''',
     "backup OAuth project persistence result"),
    ("Agent/Backup/BackupSecretsImporter.swift",
     '''                    ProviderKeychainHelper.saveRawOAuthToken(raw, instanceId: p.instanceId)
                    wrote = true''',
     '''                    if ProviderKeychainHelper.saveRawOAuthToken(raw, instanceId: p.instanceId) { wrote = true }''',
     "backup raw OAuth persistence result"),
    ("Providers/ProviderMigration.swift",
     '''        if !UserDefaults.standard.bool(forKey: oauthMigrationKey) {
            migrateOAuthTokens(store: store)
            UserDefaults.standard.set(true, forKey: oauthMigrationKey)
        }''',
     '''        if !UserDefaults.standard.bool(forKey: oauthMigrationKey) {
            if migrateOAuthTokens(store: store) {
                UserDefaults.standard.set(true, forKey: oauthMigrationKey)
            } else {
                logger.error("OAuth credential migration incomplete; keeping legacy credentials and retrying next launch")
            }
        }''',
     "OAuth migration completion gate"),
    ("Providers/ProviderMigration.swift",
     '''    private static func migrateOAuthTokens(store: ProviderConfigStore) {
        logger.info("Starting OAuth token migration to per-instance storage")''',
     '''    private static func migrateOAuthTokens(store: ProviderConfigStore) -> Bool {
        logger.info("Starting OAuth token migration to per-instance storage")
        var allPersisted = true''',
     "OAuth migration persistence result"),
    ("Providers/ProviderMigration.swift",
     '''                    ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id)
                    ClaudeOAuthManager.deleteLegacyToken()''',
     '''                    guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id) else {
                        allPersisted = false
                        logger.error("Claude OAuth migration save failed; retaining legacy token")
                        continue
                    }
                    ClaudeOAuthManager.deleteLegacyToken()''',
     "Claude migration persistence gate"),
    ("Providers/ProviderMigration.swift",
     '''                    ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id)
                    GeminiOAuthManager.deleteLegacyToken()''',
     '''                    guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id) else {
                        allPersisted = false
                        logger.error("Gemini OAuth migration save failed; retaining legacy token")
                        continue
                    }
                    GeminiOAuthManager.deleteLegacyToken()''',
     "Gemini migration persistence gate"),
    ("Providers/ProviderMigration.swift",
     '''                    ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id)
                    CodexOAuthManager.deleteLegacyToken()''',
     '''                    guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id) else {
                        allPersisted = false
                        logger.error("Codex OAuth migration save failed; retaining legacy token")
                        continue
                    }
                    CodexOAuthManager.deleteLegacyToken()''',
     "Codex migration persistence gate"),
    ("Providers/ProviderMigration.swift",
     '''            case .gemini:
                if ProviderKeychainHelper.loadOAuthToken(instanceId: instance.id, as: GeminiTokenStorage.self) != nil {
                    continue
                }
                if let token = GeminiOAuthManager.loadLegacyToken() {
                    guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id) else {
                        allPersisted = false
                        logger.error("Gemini OAuth migration save failed; retaining legacy token")
                        continue
                    }
                    GeminiOAuthManager.deleteLegacyToken()
                    logger.info("Migrated Gemini OAuth token to instance \(instance.id)")
                }
                // Migrate email and project ID from UserDefaults''',
     '''            case .gemini:
                if ProviderKeychainHelper.loadOAuthToken(instanceId: instance.id, as: GeminiTokenStorage.self) == nil {
                    if let token = GeminiOAuthManager.loadLegacyToken() {
                        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id) else {
                            allPersisted = false
                            logger.error("Gemini OAuth migration save failed; retaining legacy token")
                            continue
                        }
                        GeminiOAuthManager.deleteLegacyToken()
                        logger.info("Migrated Gemini OAuth token to instance \(instance.id)")
                    }
                }
                // Migrate email and project ID from UserDefaults''',
     "Gemini migration retries metadata after token already exists"),
    ("Providers/ProviderMigration.swift",
     '''                    ProviderKeychainHelper.saveOAuthString(email, instanceId: instance.id, account: "oauth-email")
                    UserDefaults.standard.removeObject(forKey: GeminiOAuthManager.legacyEmailKey)''',
     '''                    if ProviderKeychainHelper.saveOAuthString(email, instanceId: instance.id, account: "oauth-email") {
                        UserDefaults.standard.removeObject(forKey: GeminiOAuthManager.legacyEmailKey)
                    } else {
                        allPersisted = false
                        logger.error("Gemini OAuth email migration save failed; retaining legacy metadata")
                    }''',
     "Gemini email migration persistence gate"),
    ("Providers/ProviderMigration.swift",
     '''                    ProviderKeychainHelper.saveOAuthString(projectID, instanceId: instance.id, account: "oauth-gcp-project")
                    UserDefaults.standard.removeObject(forKey: GeminiOAuthManager.legacyProjectIDKey)''',
     '''                    if ProviderKeychainHelper.saveOAuthString(projectID, instanceId: instance.id, account: "oauth-gcp-project") {
                        UserDefaults.standard.removeObject(forKey: GeminiOAuthManager.legacyProjectIDKey)
                    } else {
                        allPersisted = false
                        logger.error("Gemini OAuth project migration save failed; retaining legacy metadata")
                    }''',
     "Gemini project migration persistence gate"),
    ("Providers/ProviderMigration.swift",
     '''        logger.info("OAuth token migration complete")
    }''',
     '''        logger.info("OAuth token migration complete success=\\(allPersisted)")
        return allPersisted
    }''',
     "OAuth migration retry result"),
]
for rel, old, new, label in changes:
    target = src / rel
    text = target.read_text(encoding="utf-8")
    text = replace_once(text, old, new, label)
    target.write_text(text, encoding="utf-8")

# MAX-only reset uses the same fallback directory and only the clone's Keychain namespace.
app_text = app.read_text(encoding="utf-8")
if "import Security\n" not in app_text:
    app_text = replace_once(app_text, "import UserNotifications\n", "import UserNotifications\nimport Security\n", "Security import for MAX reset")
reset_helper = r'''enum MinisMAXDataIsolation {
    private static let cloneBundleID = "com.openminis.devultramax"

    static func resetLocalData() {
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
        AppLogger(category: "Lifecycle").info("[MinisMAX R4] credential reset complete keychainItems=\(removedKeychainItems) fallbackDirectoryRemoved=\(removedFallbackDirectory) credentialStamps=\(removedCredentialStamps)")
    }

    private static func clearCloneKeychainItems() -> Int {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrSynchronizable as String: kSecAttrSynchronizableAny,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let items = result as? [[String: Any]] else { return 0 }
        var removed = 0
        for item in items {
            guard let service = item[kSecAttrService as String] as? String,
                  service.hasPrefix(cloneBundleID + ".") else { continue }
            var deleteQuery: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
            ]
            if let account = item[kSecAttrAccount as String] as? String {
                deleteQuery[kSecAttrAccount as String] = account
            }
            if let accessGroup = item[kSecAttrAccessGroup as String] as? String {
                deleteQuery[kSecAttrAccessGroup as String] = accessGroup
            }
            let localStatus = SecItemDelete(deleteQuery as CFDictionary)
            var syncQuery = deleteQuery
            syncQuery[kSecAttrSynchronizable as String] = true
            let syncStatus = SecItemDelete(syncQuery as CFDictionary)
            if localStatus == errSecSuccess || syncStatus == errSecSuccess { removed += 1 }
        }
        return removed
    }
}

'''
app_text = replace_once(app_text, 'private let lifecycleLog = AppLogger(category: "Lifecycle")', reset_helper + 'private let lifecycleLog = AppLogger(category: "Lifecycle")', "MAX reset cleanup helper")
app.write_text(app_text, encoding="utf-8")

restore = src / "Views/Settings/BackupAndRestoreView.swift"
restore_text = restore.read_text(encoding="utf-8")
restore_text = replace_once(restore_text, "    @State private var tab: Tab", "    @State private var tab: Tab\n    @State private var showMaxResetConfirmation = false", "MAX reset UI state")
restore_text = replace_once(restore_text,
'''        .navigationTitle("Backup & Restore")
        .navigationBarTitleDisplayMode(.inline)''',
'''        .navigationTitle("Backup & Restore")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(role: .destructive) {
                            showMaxResetConfirmation = true
                        } label: {
                            Label("Clear MAX Credentials", systemImage: "trash")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
        }
        .alert("Clear MAX Credentials?", isPresented: $showMaxResetConfirmation) {
            Button("Cancel", role: .cancel) { }
            Button("Clear MAX Credentials", role: .destructive) {
                MinisMAXDataIsolation.resetLocalData()
            }
        } message: {
            Text("This removes only Minis MAX provider credentials and credential metadata. Other MAX app data is preserved; the App Store Minis app is not affected.")
        }''',
"MAX reset UI")
restore.write_text(restore_text, encoding="utf-8")

# Normalize identity literals embedded in the patch templates as well as upstream files.
# This keeps the R5 test clone's App Group and credential namespace separate from R4.
for identity_file in src.rglob("*"):
    if identity_file.is_file() and identity_file.suffix in (".swift", ".entitlements", ".plist"):
        identity_text = identity_file.read_text(encoding="utf-8")
        normalized = re.sub(r"com\.openminis\.devultramax(?!\.r[0-9]+)", bundle_id, identity_text)
        if normalized != identity_text:
            identity_file.write_text(normalized, encoding="utf-8")
ps = (src / "Providers/ProviderConfigStore.swift").read_text(encoding="utf-8")
app_text = app.read_text(encoding="utf-8")
assert "com.openminis.app.provider." not in ps, "NO-GO: original provider Keychain namespace remains"
assert ps.count(bundle_id + ".provider.") >= 11, "NO-GO: MAX provider Keychain namespace incomplete"
assert "protectedFallbackSaved=" in ps, "NO-GO: actual Keychain status/fallback result logging missing"
assert "FileProtectionType.completeUntilFirstUserAuthentication" in ps, "NO-GO: iOS file data protection missing"
assert "try directory.setResourceValues(values)" in ps and "try temporaryURL.setResourceValues(values)" in ps, "NO-GO: credential backup exclusion must fail closed"
assert 'var directory = support.appendingPathComponent("MinisMAXCredentialFallback", isDirectory: true)' in ps, "NO-GO: fallback directory URL must be mutable for resource protection"
assert 'var temporaryURL = directory.appendingPathComponent(UUID().uuidString + ".credential.tmp", isDirectory: false)' in ps, "NO-GO: fallback temporary URL must be mutable for backup exclusion"
assert "fallbackAttempted = true" not in ps, "NO-GO: obsolete sync-dependent fallback remains"
assert "FileManager.default.setAttributes(" in ps, "NO-GO: protection must be enforced on pre-existing fallback directory"
assert ps.count("fallbackSavedBeforeKeychain =") == 4, "NO-GO: every credential writer must stage fallback before deleting old Keychain items"
assert "stageCloneCredentialFallback" in ps and "keychainStatus != errSecItemNotFound" in ps, "NO-GO: preflight must preserve existing Keychain/fallback credentials before destructive writes"
assert "try? FileManager.default.removeItem(at: url)" not in ps, "NO-GO: fallback write failure must not delete the previously committed credential"
assert "return addStatus == errSecSuccess || fallbackSaved" in ps, "NO-GO: API key persistence result missing"
assert "return status == errSecSuccess || fallbackSaved" in ps, "NO-GO: raw OAuth persistence result missing"
assert "return keychainStatus == errSecSuccess || fallbackSaved" in ps, "NO-GO: OAuth string persistence result missing"
assert "return addStatus == errSecSuccess || fallbackSaved" in ps, "NO-GO: API key persistence result missing"
assert "return status == errSecSuccess || fallbackSaved" in ps, "NO-GO: raw OAuth persistence result missing"
assert "return keychainStatus == errSecSuccess || fallbackSaved" in ps, "NO-GO: OAuth string persistence result missing"
assert 'for name in ["Documents", "Library", "tmp"]' not in app_text, "NO-GO: reset still wipes broad app directories"
assert "removePersistentDomain(forName: cloneBundleID)" not in app_text, "NO-GO: reset removes unrelated MAX preferences"
assert 'for name in ["Documents", "Library", "tmp"]' not in app_text, "NO-GO: MAX reset must not wipe broad app directories"
assert 'removePersistentDomain(forName: cloneBundleID)' not in app_text, "NO-GO: MAX credential reset must preserve unrelated app preferences"
print("PASS R4: local-only Keychain first; no synchronization-attribute-dependent fallback")
print("PASS R4: OSStatus logging + protected, backup-excluded MAX file fallback for API/OAuth credentials")
print("PASS R4: read, logout/delete, and explicit MAX-only cleanup use the same fallback path")
print("PASS R4: OAuth login only completes when persistence succeeds")

# Negative controls: absolutely no production App Group/CloudKit/FileProvider
# identity can remain in this independent clone.
bad = []
for p in src.rglob("*"):
    if p.is_file() and p.suffix in (".swift", ".entitlements", ".plist"):
        txt = p.read_text(encoding="utf-8")
        for value in (old_group, old_icloud, old_fp, "com.openminis.app"):
            if value in txt:
                bad.append((str(p),value))
if bad:
    raise RuntimeError("NO-GO: original App Store group identities remain: "+repr(bad[:8]))
assert "minisIsolatedContainerBase" in budget.read_text()
assert "FileProvider registration skipped" in app.read_text()
print("PASS: app-group SIGTRAP guard and isolation; source files modified",len(changed)+3)
print("NO CHANGE: original installed App Store app, user data, or signing identity")
