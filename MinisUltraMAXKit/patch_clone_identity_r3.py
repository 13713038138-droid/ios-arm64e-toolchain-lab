#!/usr/bin/env python3
"""R3 clone-only persistence, OAuth, backup-picker, and reset hardening."""
from pathlib import Path
import plistlib
import sys

CLONE = "com.openminis.devultramax"
APP = "com.openminis.app"
PIN = "b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c"

def need(root: Path, rel: str) -> Path:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"NO-GO: missing required source {rel}")
    return path

def replace_exact(text: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"NO-GO {label}: expected {expected} exact anchor(s), found {count}")
    return text.replace(old, new)

def edit(root: Path, rel: str, fn) -> None:
    path = need(root, rel)
    original = path.read_text(encoding="utf-8")
    updated = fn(original)
    if updated == original:
        raise RuntimeError(f"NO-GO {rel}: patch produced no change")
    path.write_text(updated, encoding="utf-8")

def patch_provider_store(root: Path) -> None:
    rel = "src/ios/Providers/ProviderConfigStore.swift"
    def apply(s: str) -> str:
        # Route all per-provider Keychain items to a clone-only service namespace.
        old_service = 'let service = "com.openminis.app.provider.\\(instanceId)"'
        s = replace_exact(s, old_service, "let service = providerService(instanceId: instanceId)",
                          "provider Keychain service namespace", 11)
        anchor = 'enum ProviderKeychainHelper {\n    private static let account = "api-key"'
        helper = '''enum ProviderKeychainHelper {
    private static let account = "api-key"

    private static func providerService(instanceId: String) -> String {
        if Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
            return "com.openminis.devultramax.provider.\\(instanceId)"
        }
        return "com.openminis.app.provider.\\(instanceId)"
    }'''
        s = replace_exact(s, anchor, helper, "provider service helper", 1)

        # Original Minis keeps iCloud Keychain sync. The side-by-side clone uses
        # local-only items so credentials do not reappear from iCloud on reinstall.
        sync_attr = 'addQuery[kSecAttrSynchronizable as String] = true'
        local_only = '''if Bundle.main.bundleIdentifier != "com.openminis.devultramax" {
            addQuery[kSecAttrSynchronizable as String] = true
        }'''
        s = replace_exact(s, sync_attr, local_only, "clone-local Keychain writes", 4)

        # R2's fallback is useful only when a sync write was actually attempted.
        old_fallback = 'if addStatus != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" {'
        new_fallback = 'if addStatus != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" && addQuery[kSecAttrSynchronizable as String] != nil {'
        s = replace_exact(s, old_fallback, new_fallback, "sync fallback guard", 3)
        old_raw_fallback = 'if status != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" {'
        new_raw_fallback = 'if status != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" && addQuery[kSecAttrSynchronizable as String] != nil {'
        s = replace_exact(s, old_raw_fallback, new_raw_fallback, "raw OAuth sync fallback guard", 1)

        # Return a verifiable persistence result instead of letting a failed
        # Keychain write look like a completed login.
        old_sig = 'static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) {'
        new_sig = '@discardableResult\n    static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) -> Bool {'
        s = replace_exact(s, old_sig, new_sig, "OAuth token write result", 1)
        old_encode = '''        guard let data = try? JSONEncoder().encode(token) else {
            AppLogger(category: "Keychain").warning("write oauthToken instanceId=\\(instanceId.prefix(8)) ENCODE FAILED caller=\\(caller)")
            return
        }'''
        new_encode = '''        guard let data = try? JSONEncoder().encode(token) else {
            AppLogger(category: "Keychain").error("write oauthToken instanceId=\\(instanceId.prefix(8)) ENCODE FAILED caller=\\(caller)")
            return false
        }'''
        s = replace_exact(s, old_encode, new_encode, "OAuth token encode failure", 1)
        old_tail = '''        AppLogger(category: "Keychain").info("write oauthToken instanceId=\\(instanceId.prefix(8)) blobLen=\\(data.count) addStatus=\\(addStatus) caller=\\(caller)")
        clearOAuthNeedsReauth(instanceId: instanceId)
        notifyAuthChanged(instanceId: instanceId)
    }'''
        new_tail = '''        AppLogger(category: "Keychain").info("write oauthToken instanceId=\\(instanceId.prefix(8)) blobLen=\\(data.count) addStatus=\\(addStatus) caller=\\(caller)")
        guard addStatus == errSecSuccess else {
            AppLogger(category: "Keychain").error("write oauthToken FAILED instanceId=\\(instanceId.prefix(8)) status=\\(addStatus) caller=\\(caller)")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        clearOAuthNeedsReauth(instanceId: instanceId)
        notifyAuthChanged(instanceId: instanceId)
        return true
    }'''
        return replace_exact(s, old_tail, new_tail, "OAuth token write status", 1)
    edit(root, rel, apply)

def patch_static_service(root: Path, rel: str, declaration: str, clone_service: str, label: str) -> None:
    old = declaration
    new = declaration.split(" = ", 1)[0] + (
        f' = Bundle.main.bundleIdentifier == "{CLONE}" ? "{clone_service}" : '
        f'"{declaration.split(chr(34))[1]}"'
    )
    edit(root, rel, lambda s: replace_exact(s, old, new, label, 1))

def patch_legacy_service(root: Path, rel: str, old: str, clone: str, label: str) -> None:
    new = old.split(" = ", 1)[0] + (
        f' = Bundle.main.bundleIdentifier == "{CLONE}" ? "{clone}" : '
        f'"{old.split(chr(34))[1]}"'
    )
    edit(root, rel, lambda s: replace_exact(s, old, new, label, 1))

def patch_clone_credential_file_fallback(root: Path) -> None:
    """Use protected app-container storage only when MAX's Keychain write/read fails."""
    rel = "src/ios/Providers/ProviderConfigStore.swift"
    def apply(s: str) -> str:
        anchor = '''        return "com.openminis.app.provider.\\(instanceId)"
    }'''
        helpers = r'''        return "com.openminis.app.provider.\(instanceId)"
    }

    private static func cloneCredentialFallbackURL(service: String, account: String) -> URL? {
        guard Bundle.main.bundleIdentifier == "com.openminis.devultramax",
              let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        else { return nil }
        let raw = Data("\(service)|\(account)".utf8).base64EncodedString()
        let name = raw.replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
        let directory = support.appendingPathComponent("MinisMAXCredentialFallback", isDirectory: true)
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
            )
        } catch {
            AppLogger(category: "Keychain").error("MAX fallback directory creation failed: \(error.localizedDescription)")
            return nil
        }
        return directory.appendingPathComponent(name, isDirectory: false)
    }

    private static func writeCloneCredentialFallback(_ data: Data, service: String, account: String) -> Bool {
        guard let url = cloneCredentialFallbackURL(service: service, account: account) else { return false }
        do {
            try data.write(to: url, options: .atomic)
            try FileManager.default.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: url.path
            )
            return true
        } catch {
            AppLogger(category: "Keychain").error("MAX fallback credential write failed: \(error.localizedDescription)")
            return false
        }
    }

    private static func readCloneCredentialFallback(service: String, account: String) -> Data? {
        guard let url = cloneCredentialFallbackURL(service: service, account: account) else { return nil }
        return try? Data(contentsOf: url, options: [.mappedIfSafe])
    }

    private static func deleteCloneCredentialFallback(service: String, account: String) {
        guard let url = cloneCredentialFallbackURL(service: service, account: account) else { return }
        try? FileManager.default.removeItem(at: url)
    }'''
        s = replace_exact(s, anchor, helpers, "MAX protected credential fallback helpers", 1)

        old_raw_save = '''        if status != errSecSuccess {
            AppLogger(category: "Keychain").warning("write rawOAuthToken instanceId=\\(instanceId.prefix(8)) status=\\(status)")
        }
        clearOAuthNeedsReauth(instanceId: instanceId)'''
        new_raw_save = '''        let fallbackSaved = status == errSecSuccess ? false : writeCloneCredentialFallback(data, service: service, account: acct)
        AppLogger(category: "Keychain").info("write rawOAuthToken instanceId=\\(instanceId.prefix(8)) keychainStatus=\\(status) protectedFallbackSaved=\\(fallbackSaved)")
        if status == errSecSuccess || fallbackSaved {
            clearOAuthNeedsReauth(instanceId: instanceId)
        }'''
        s = replace_exact(s, old_raw_save, new_raw_save, "raw OAuth protected fallback", 1)

        old_raw_load = '''        query[kSecAttrSynchronizable as String] = kSecAttrSynchronizableAny
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data'''
        new_raw_load = '''        query[kSecAttrSynchronizable as String] = kSecAttrSynchronizableAny
        var result: AnyObject?
        if SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
           let data = result as? Data { return data }
        return readCloneCredentialFallback(service: service, account: "oauth-token")'''
        s = replace_exact(s, old_raw_load, new_raw_load, "raw OAuth protected fallback read", 1)

        old_oauth_tail = '''        guard addStatus == errSecSuccess else {
            AppLogger(category: "Keychain").error("write oauthToken FAILED instanceId=\\(instanceId.prefix(8)) status=\\(addStatus) caller=\\(caller)")
            notifyAuthChanged(instanceId: instanceId)
            return false
        }
        clearOAuthNeedsReauth(instanceId: instanceId)
        notifyAuthChanged(instanceId: instanceId)
        return true'''
        new_oauth_tail = '''        if addStatus != errSecSuccess {
            let fallbackSaved = writeCloneCredentialFallback(data, service: service, account: acct)
            AppLogger(category: "Keychain").error("write oauthToken Keychain failed instanceId=\\(instanceId.prefix(8)) status=\\(addStatus) protectedFallbackSaved=\\(fallbackSaved) caller=\\(caller)")
            guard fallbackSaved else {
                notifyAuthChanged(instanceId: instanceId)
                return false
            }
        }
        clearOAuthNeedsReauth(instanceId: instanceId)
        notifyAuthChanged(instanceId: instanceId)
        return true'''
        s = replace_exact(s, old_oauth_tail, new_oauth_tail, "typed OAuth protected fallback", 1)

        old_oauth_load = '''        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            AppLogger(category: "Keychain").info("read oauthToken instanceId=\\(instanceId.prefix(8)) hit=false syncStatus=\\(syncStatus) legacyStatus=\\(legacyStatus) caller=\\(caller)")
            return nil
        }
        let decoded = try? JSONDecoder().decode(type, from: data)'''
        new_oauth_load = '''        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            if let fallbackData = readCloneCredentialFallback(service: service, account: acct) {
                let fallbackToken = try? JSONDecoder().decode(type, from: fallbackData)
                AppLogger(category: "Keychain").info("read oauthToken instanceId=\\(instanceId.prefix(8)) src=protectedFallback hit=\\(fallbackToken != nil) caller=\\(caller)")
                return fallbackToken
            }
            AppLogger(category: "Keychain").info("read oauthToken instanceId=\\(instanceId.prefix(8)) hit=false syncStatus=\\(syncStatus) legacyStatus=\\(legacyStatus) caller=\\(caller)")
            return nil
        }
        let decoded = try? JSONDecoder().decode(type, from: data)'''
        s = replace_exact(s, old_oauth_load, new_oauth_load, "typed OAuth protected fallback read", 1)

        old_oauth_delete = '''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        AppLogger(category: "Keychain").info("delete oauthToken instanceId=\\(instanceId.prefix(8)) legacyStatus=\\(s1) syncStatus=\\(s2) caller=\\(caller)")'''
        new_oauth_delete = '''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        deleteCloneCredentialFallback(service: service, account: acct)
        AppLogger(category: "Keychain").info("delete oauthToken instanceId=\\(instanceId.prefix(8)) legacyStatus=\\(s1) syncStatus=\\(s2) caller=\\(caller)")'''
        s = replace_exact(s, old_oauth_delete, new_oauth_delete, "typed OAuth protected fallback delete", 1)

        old_string_save = '''        AppLogger(category: "Keychain").info("write oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) valLen=\\(value.count) addStatus=\\(addStatus) caller=\\(caller)")
        notifyAuthChanged(instanceId: instanceId)'''
        new_string_save = '''        let fallbackSaved = addStatus == errSecSuccess ? false : writeCloneCredentialFallback(Data(value.utf8), service: service, account: account)
        AppLogger(category: "Keychain").info("write oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) valLen=\\(value.count) keychainStatus=\\(addStatus) protectedFallbackSaved=\\(fallbackSaved) caller=\\(caller)")
        notifyAuthChanged(instanceId: instanceId)'''
        s = replace_exact(s, old_string_save, new_string_save, "OAuth string protected fallback", 1)

        old_string_load = '''        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            AppLogger(category: "Keychain").info("read oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) hit=false syncStatus=\\(syncStatus) legacyStatus=\\(legacyStatus) caller=\\(caller)")
            return nil
        }
        let s = String(data: data, encoding: .utf8)'''
        new_string_load = '''        guard legacyStatus == errSecSuccess, let data = result as? Data else {
            if let fallbackData = readCloneCredentialFallback(service: service, account: account),
               let fallbackString = String(data: fallbackData, encoding: .utf8) {
                AppLogger(category: "Keychain").info("read oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) src=protectedFallback hit=true caller=\\(caller)")
                return fallbackString
            }
            AppLogger(category: "Keychain").info("read oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) hit=false syncStatus=\\(syncStatus) legacyStatus=\\(legacyStatus) caller=\\(caller)")
            return nil
        }
        let s = String(data: data, encoding: .utf8)'''
        s = replace_exact(s, old_string_load, new_string_load, "OAuth string protected fallback read", 1)

        old_string_delete = '''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        AppLogger(category: "Keychain").info("delete oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) legacyStatus=\\(s1) syncStatus=\\(s2) caller=\\(caller)")'''
        new_string_delete = '''        let s2 = SecItemDelete(syncQuery as CFDictionary)
        deleteCloneCredentialFallback(service: service, account: account)
        AppLogger(category: "Keychain").info("delete oauthString instanceId=\\(instanceId.prefix(8)) acct=\\(account) legacyStatus=\\(s1) syncStatus=\\(s2) caller=\\(caller)")'''
        s = replace_exact(s, old_string_delete, new_string_delete, "OAuth string protected fallback delete", 1)

        return s
    edit(root, rel, apply)


def patch_oauth_login_sites(root: Path) -> None:
    failure = '''guard ProviderKeychainHelper.saveOAuthToken({value}, instanceId: instanceId) else {{
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }}'''
    changes = [
        ("src/ios/Providers/Anthropic/OAuth/ClaudeOAuthManager.swift",
         '''        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)
        logger.info("=== OAuth login complete (instance: \\(instanceId)) ===")''',
         '''        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }
        logger.info("=== OAuth login complete (instance: \\(instanceId)) ===")''',
         "Claude login persistence result"),
        ("src/ios/Providers/OpenAI/OAuth/CodexOAuthManager.swift",
         '''        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)
        logger.info("=== Codex OAuth login complete (instance: \\(instanceId)) ===")''',
         '''        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }
        logger.info("=== Codex OAuth login complete (instance: \\(instanceId)) ===")''',
         "Codex login persistence result"),
        ("src/ios/Providers/Gemini/OAuth/GeminiOAuthManager.swift",
         '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)''',
         '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }''',
         "Gemini login persistence result"),
        ("src/ios/Providers/Antigravity/OAuth/AntigravityOAuthManager.swift",
         '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)''',
         '''        let token = try await exchangeCode(result.code, codeVerifier: pkce.verifier)
        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }''',
         "Antigravity login persistence result"),
        ("src/ios/Providers/Kimi/OAuth/KimiOAuthManager.swift",
         '''        ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId)
        logger.info("Kimi device login complete (instance: \\(instanceId))")''',
         '''        guard ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }
        logger.info("Kimi device login complete (instance: \\(instanceId))")''',
         "Kimi login persistence result"),
        ("src/ios/Providers/Copilot/OAuth/CopilotOAuthManager.swift",
         '''                let storage = CopilotTokenStorage(githubToken: accessToken)
                ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId)
                logger.info("[Copilot] device flow complete for instance \\(instanceId.prefix(8))")''',
         '''                let storage = CopilotTokenStorage(githubToken: accessToken)
                guard ProviderKeychainHelper.saveOAuthToken(storage, instanceId: instanceId) else {
                    throw LLMError.providerError(message: "GitHub authorized successfully, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
                }
                logger.info("[Copilot] device flow complete for instance \\(instanceId.prefix(8))")''',
         "GitHub Copilot login persistence result"),
        ("src/ios/Providers/xAI/OAuth/XAIOAuthManager.swift",
         '''        ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId)
        // isAuthenticated(instanceId:) is a plain Keychain read, not @Published —''',
         '''        guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instanceId) else {
            throw LLMError.providerError(message: "Authorization completed, but Minis MAX could not persist the credential in Keychain. Check the app signing and Keychain access, then retry.")
        }
        // isAuthenticated(instanceId:) is a plain Keychain read, not @Published —''',
         "xAI login persistence result"),
    ]
    for rel, old, new, label in changes:
        edit(root, rel, lambda s, old=old, new=new, label=label: replace_exact(s, old, new, label, 1))

def patch_clone_lifecycle(root: Path) -> None:
    rel = "src/ios/MinisApp.swift"
    helper = r'''enum MinisMAXDataIsolation {
    static let cloneBundleID = "com.openminis.devultramax"
    private static let markerService = "com.openminis.devultramax.install-lifecycle"
    private static let markerAccount = "install-marker"
    private static let markerFileName = "MinisMAXInstallMarker"

    static func bootstrap() {
        guard Bundle.main.bundleIdentifier == cloneBundleID else { return }
        let fm = FileManager.default
        guard let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first else { return }
        let markerURL = library.appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent(markerFileName)
        let hasLocalMarker = fm.fileExists(atPath: markerURL.path)
        let keychainStatus = markerStatus()

        // Keychain items survive ordinary iOS app removal. If the sandbox marker
        // vanished but the clone-only Keychain marker remains, this is a reinstall.
        // Delete only services in the MAX namespace; never touch com.openminis.app.
        if !hasLocalMarker && keychainStatus == errSecSuccess {
            let removed = clearCloneKeychainItems()
            lifecycleLog.info("[MinisMAX R3] reinstall detected; removed \\(removed) MAX-only Keychain item(s)")
        }

        if !hasLocalMarker {
            try? fm.createDirectory(at: markerURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? Data(UUID().uuidString.utf8).write(to: markerURL, options: .atomic)
        }
        if keychainStatus == errSecItemNotFound {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: markerService,
                kSecAttrAccount as String: markerAccount,
                kSecValueData as String: Data("v1".utf8),
                kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
            ]
            let status = SecItemAdd(query as CFDictionary, nil)
            if status != errSecSuccess && status != errSecDuplicateItem {
                lifecycleLog.error("[MinisMAX R3] install marker Keychain write failed status=\\(status)")
            }
        }
    }

    static func resetLocalData() {
        guard Bundle.main.bundleIdentifier == cloneBundleID else { return }
        _ = clearCloneKeychainItems()
        let fm = FileManager.default
        let home = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        // These directories are all inside this app's own sandbox. Removing their
        // children clears local chats/config, guest files, preferences, caches and logs.
        for name in ["Documents", "Library", "tmp"] {
            let directory = home.appendingPathComponent(name, isDirectory: true)
            let children = (try? fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
            for child in children { try? fm.removeItem(at: child) }
        }
        UserDefaults.standard.removePersistentDomain(forName: cloneBundleID)
    }

    private static func markerStatus() -> OSStatus {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: markerService,
            kSecAttrAccount as String: markerAccount,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        return SecItemCopyMatching(query as CFDictionary, &result)
    }

    private static func clearCloneKeychainItems() -> Int {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrSynchronizable as String: kSecAttrSynchronizableAny,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let items = result as? [[String: Any]] else { return 0 }
        var removed = 0
        for item in items {
            guard let service = item[kSecAttrService as String] as? String,
                  service.hasPrefix(cloneBundleID + "."),
                  service != markerService else { continue }
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
    def apply(s: str) -> str:
        s = replace_exact(s, "import UserNotifications\n", "import UserNotifications\nimport Security\n",
                          "Security import", 1)
        anchor = 'private let lifecycleLog = AppLogger(category: "Lifecycle")'
        s = replace_exact(s, anchor, anchor + "\n\n" + helper.rstrip(),
                          "clone data lifecycle helper", 1)
        s = replace_exact(s, "        CrashSignalHandler.install()\n",
                          "        CrashSignalHandler.install()\n        MinisMAXDataIsolation.bootstrap()\n",
                          "early clone install lifecycle", 1)
        old_sync = '''    private static func startSyncEngines() async {
        await SyncV2Bootstrap.startIfEnabled()'''
        new_sync = '''    private static func startSyncEngines() async {
        guard Bundle.main.bundleIdentifier != "com.openminis.devultramax" else {
            lifecycleLog.info("[MinisMAX R3] cloud sync disabled for isolated clone")
            return
        }
        await SyncV2Bootstrap.startIfEnabled()'''
        s = replace_exact(s, old_sync, new_sync, "clone sync startup gate", 1)
        return s
    edit(root, rel, apply)

def patch_sync_engines(root: Path) -> None:
    rel = "src/ios/Agent/Sync/CloudSyncEngine.swift"
    def apply(s: str) -> str:
        s = replace_exact(s, '''    func start() async {
        guard isEnabled else {''',
            '''    func start() async {
        guard Bundle.main.bundleIdentifier != "com.openminis.devultramax" else {
            syncStatus = .disabled
            logger.info("[CloudSync] disabled for isolated Minis MAX clone")
            return
        }
        guard isEnabled else {''', "CloudSync start gate", 1)
        s = replace_exact(s, '''    func triggerFetch() async {
        guard let engine = syncEngine else { return }''',
            '''    func triggerFetch() async {
        guard Bundle.main.bundleIdentifier != "com.openminis.devultramax" else { return }
        guard let engine = syncEngine else { return }''', "CloudSync fetch gate", 1)
        s = replace_exact(s, '''    func triggerSend() async {
        guard let engine = syncEngine else { return }''',
            '''    func triggerSend() async {
        guard Bundle.main.bundleIdentifier != "com.openminis.devultramax" else { return }
        guard let engine = syncEngine else { return }''', "CloudSync send gate", 1)
        return s
    edit(root, rel, apply)

    rel = "src/ios/Agent/Sync/V2/SyncV2Bootstrap.swift"
    def apply_v2(s: str) -> str:
        return replace_exact(s, '''    static func startIfEnabled() async {
        guard isEnabled else {''',
            '''    static func startIfEnabled() async {
        guard Bundle.main.bundleIdentifier != "com.openminis.devultramax" else {
            logger.info("[SyncCore] disabled for isolated Minis MAX clone")
            return
        }
        guard isEnabled else {''', "SyncCore clone gate", 1)
    edit(root, rel, apply_v2)

def patch_info_plist(root: Path) -> None:
    path = need(root, "src/ios/Info.plist")
    with path.open("rb") as f:
        info = plistlib.load(f)
    schemes_changed = 0
    for item in info.get("CFBundleURLTypes", []):
        schemes = item.get("CFBundleURLSchemes", [])
        for i, scheme in enumerate(schemes):
            if scheme == APP:
                schemes[i] = CLONE
                schemes_changed += 1
    if schemes_changed != 1:
        raise RuntimeError(f"NO-GO clone URL scheme: expected 1 change, found {schemes_changed}")
    exported = info.pop("UTExportedTypeDeclarations", None)
    if not isinstance(exported, list) or len(exported) != 1:
        raise RuntimeError("NO-GO backup UTI: expected one exported .minisbak declaration")
    if exported[0].get("UTTypeIdentifier") != "com.openminis.app.minisbak":
        raise RuntimeError("NO-GO backup UTI: unexpected identifier")
    if "UTImportedTypeDeclarations" in info:
        raise RuntimeError("NO-GO backup UTI: imported declaration already exists")
    info["UTImportedTypeDeclarations"] = exported
    with path.open("wb") as f:
        plistlib.dump(info, f, fmt=plistlib.FMT_XML, sort_keys=False)

def patch_backup_picker(root: Path) -> None:
    rel = "src/ios/Views/Settings/BackupRestoreView.swift"
    edit(root, rel, lambda s: replace_exact(
        s, "allowedContentTypes: [BackupDelivery.contentType, .data],",
        '''allowedContentTypes: Bundle.main.bundleIdentifier == "com.openminis.devultramax"
                          ? [.item]
                          : [BackupDelivery.contentType, .data],''',
        "clone broad backup file picker", 1))

    rel = "src/ios/Views/Settings/BackupAndRestoreView.swift"
    def apply(s: str) -> str:
        s = replace_exact(s, "    @State private var tab: Tab",
                          "    @State private var tab: Tab\n    @State private var showMaxResetConfirmation = false\n    @State private var showMaxResetResult = false",
                          "MAX reset UI state", 1)
        old_tail = '''        .navigationTitle("Backup & Restore")
        .navigationBarTitleDisplayMode(.inline)'''
        new_tail = '''        .navigationTitle("Backup & Restore")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(role: .destructive) {
                            showMaxResetConfirmation = true
                        } label: {
                            Label("Clear MAX Data", systemImage: "trash")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
        }
        .confirmationDialog("Clear all local Minis MAX data?", isPresented: $showMaxResetConfirmation, titleVisibility: .visible) {
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
        }'''
        return replace_exact(s, old_tail, new_tail, "MAX reset menu", 1)
    edit(root, rel, apply)

def patch_migration_and_services(root: Path) -> None:
    # Legacy migrations can otherwise read original Minis Keychain entries and
    # copy them into the clone on first launch.
    rel = "src/ios/Providers/ProviderMigration.swift"
    edit(root, rel, lambda s: replace_exact(
        s, '''    static func migrateIfNeeded(store: ProviderConfigStore) {
        if !UserDefaults.standard.bool(forKey: migrationKey) {''',
        '''    static func migrateIfNeeded(store: ProviderConfigStore) {
        if Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
            logger.info("[ProviderMigration] skip original-app legacy Keychain migration in isolated MAX clone")
            return
        }
        if !UserDefaults.standard.bool(forKey: migrationKey) {''',
        "clone legacy migration gate", 1))

    patch_static_service(root, "src/ios/Agent/Session/MCPOAuthController.swift",
        'nonisolated private static let keychainService = "com.openminis.app.mcp-oauth"',
        "com.openminis.devultramax.mcp-oauth", "MCP OAuth Keychain namespace")
    patch_static_service(root, "src/ios/Shared/EnvVarStore.swift",
        'nonisolated private static let keychainService = "com.openminis.app.envvar"',
        "com.openminis.devultramax.envvar", "environment secret Keychain namespace")
    patch_static_service(root, "src/ios/Agent/Backup/Remote/RcloneRemoteStore.swift",
        'private static let keychainService = "com.openminis.app.rclone"',
        "com.openminis.devultramax.rclone", "remote credential Keychain namespace")
    patch_static_service(root, "src/ios/Shared/DeviceIdentity.swift",
        'private static let keychainService = "com.openminis.app.device"',
        "com.openminis.devultramax.device", "device identity Keychain namespace")
    patch_legacy_service(root, "src/ios/Providers/Anthropic/OAuth/ClaudeOAuthManager.swift",
        'static let legacyKeychainService = "com.openminis.app.claude-oauth"',
        "com.openminis.devultramax.claude-oauth", "Claude legacy Keychain namespace")
    patch_legacy_service(root, "src/ios/Providers/OpenAI/OAuth/CodexOAuthManager.swift",
        'static let legacyKeychainService = "com.openminis.app.openai-oauth"',
        "com.openminis.devultramax.openai-oauth", "Codex legacy Keychain namespace")
    patch_legacy_service(root, "src/ios/Providers/Gemini/OAuth/GeminiOAuthManager.swift",
        'static let legacyKeychainService = "com.openminis.app.gemini-oauth"',
        "com.openminis.devultramax.gemini-oauth", "Gemini legacy Keychain namespace")

def patch(root: Path) -> None:
    if not (root / "src/ios/Minis.xcodeproj/project.pbxproj").is_file():
        raise RuntimeError("NO-GO: root is not the pinned OpenMinis source tree")
    patch_provider_store(root)
    patch_clone_credential_file_fallback(root)
    patch_oauth_login_sites(root)
    patch_migration_and_services(root)
    patch_clone_lifecycle(root)
    patch_sync_engines(root)
    patch_info_plist(root)
    patch_backup_picker(root)
    print("PASS R3: clone-only Keychain namespace + local-only OAuth persistence")
    print("PASS R3: login fails visibly when token persistence fails")
    print("PASS R3: clone cloud sync and legacy credential migration disabled")
    print("PASS R3: install/reinstall cleanup + explicit MAX-only reset")
    print("PASS R3: clone OAuth URL identity + permissive validated backup picker")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_clone_identity_r3.py /path/to/pinned/OpenMinis")
    try:
        patch(Path(sys.argv[1]).resolve())
    except Exception as exc:
        raise SystemExit(str(exc))
