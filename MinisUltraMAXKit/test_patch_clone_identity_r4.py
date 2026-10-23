#!/usr/bin/env python3
"""R4 static release gates for credential persistence and clone-only reset."""
from pathlib import Path
import sys

CLONE = "com.openminis.devultramax"

def require(condition, message):
    if not condition:
        raise SystemExit("NO-GO R4: " + message)

def main(root: Path):
    store = (root / "src/ios/Providers/ProviderConfigStore.swift").read_text(encoding="utf-8")
    app = (root / "src/ios/MinisApp.swift").read_text(encoding="utf-8")
    reset_ui = (root / "src/ios/Views/Settings/BackupAndRestoreView.swift").read_text(encoding="utf-8")
    add = (root / "src/ios/Views/Providers/AddProviderView.swift").read_text(encoding="utf-8")
    collection = (root / "src/ios/Shared/Config/Collections/ProvidersCollection.swift").read_text(encoding="utf-8")
    detail = (root / "src/ios/Views/Providers/ProviderInstanceDetailView.swift").read_text(encoding="utf-8")
    openrouter = (root / "src/ios/Providers/OpenRouter/OAuth/OpenRouterOAuthManager.swift").read_text(encoding="utf-8")
    backup = (root / "src/ios/Agent/Backup/BackupSecretsImporter.swift").read_text(encoding="utf-8")
    migration = (root / "src/ios/Providers/ProviderMigration.swift").read_text(encoding="utf-8")
    destinations = (root / "src/ios/Agent/Backup/BackupDestinations.swift").read_text(encoding="utf-8")
    restore_view = (root / "src/ios/Views/Settings/BackupRestoreView.swift").read_text(encoding="utf-8")
    detail_view = (root / "src/ios/Views/Settings/BackupDestinationDetailView.swift").read_text(encoding="utf-8")

    require('return "com.openminis.devultramax.provider.\\(instanceId)"' in store,
            "MAX Keychain namespace missing")
    require('return "com.openminis.app.provider.\\(instanceId)"' in store,
            "original Minis Keychain namespace was not preserved")
    require(store.count('if Bundle.main.bundleIdentifier != "com.openminis.devultramax"') >= 4,
            "original app's synchronizable Keychain behavior was not preserved")
    require("SHA256.hash(data: key)" in store and 'name + ".credential"' in store,
            "fallback file names are not opaque and hashed")
    for marker in [
        "FileManager.default.setAttributes(",
        "FileProtectionType.completeUntilFirstUserAuthentication",
        "values.isExcludedFromBackup = true",
        "clearCloneCredentialFallbackDirectory()",
    ]:
        require(marker in store, "protected fallback invariant missing: " + marker)

    signatures = [
        "static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) -> Bool {",
        "static func saveRawOAuthToken(_ data: Data, instanceId: String) -> Bool {",
        "static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) -> Bool {",
        "static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {",
    ]
    for signature in signatures:
        require(signature in store, "save result signature missing: " + signature)
    require(store.count("let fallbackStage = stageCloneCredentialFallback") >= 4 and
            store.count("fallbackSavedBeforeKeychain = fallbackStage.saved") >= 4,
            "all credential writes must stage a protected fallback before destructive Keychain replacement")
    require("stageCloneCredentialFallback" in store and
            "keychainStatus != errSecItemNotFound" in store,
            "preflight must preserve existing Keychain credentials when fallback staging fails")
    require("replaceItemAt(url, withItemAt: temporaryURL)" in store and
            "removeItem(at: temporaryURL)" in store and
            "try? FileManager.default.removeItem(at: url)" not in store,
            "fallback writes must atomically replace the credential without deleting the last valid copy")
    require("static func loadRawOAuthToken(instanceId: String) -> Data? {" in store,
            "raw OAuth load method was lost while replacing its writer")
    require("nonisolated static func listPackages(folderId: UUID? = nil) async -> [FoundPackage]" in destinations and
            "await Task.detached(priority: .userInitiated)" in destinations,
            "mounted backup package scanning must remain off-main while respecting actor isolation")
    require("let found = await BackupDestinations.listPackages(folderId: id)" in restore_view and
            "folderPackages = await BackupDestinations.listPackages(folderId: id)" in detail_view,
            "backup restore screens must await the actor-safe package listing")
    require(store.count("static func loadRawOAuthToken(instanceId: String) -> Data? {") == 1,
            "raw OAuth load function was deleted or duplicated by the writer patch")

    methods = [
        ("static func loadAPIKey", "static func deleteAPIKey"),
        ("static func loadRawOAuthToken", "@discardableResult\n    static func saveOAuthToken"),
        ("static func loadOAuthToken<T: Codable>", "static func deleteOAuthToken"),
        ("static func loadOAuthString", "static func deleteOAuthString"),
    ]
    token_delete_start = store.index("static func deleteOAuthToken")
    token_delete_end = store.index("// MARK: - OAuth", token_delete_start)
    require("deleteCloneCredentialFallback(service: service, account: acct)" in store[token_delete_start:token_delete_end],
            "OAuth sign-out must delete the protected fallback alongside Keychain")
    string_delete_start = store.index("static func deleteOAuthString")
    string_delete_end = store.index("\n    }", string_delete_start)
    require("deleteCloneCredentialFallback(service: service, account: account)" in store[string_delete_start:string_delete_end],
            "OAuth metadata sign-out must delete the protected fallback alongside Keychain")
    for start, end in methods:
        begin = store.index(start)
        finish = store.index(end, begin + len(start))
        body = store[begin:finish]
        require("readCloneCredentialFallback" in body and
                body.index("readCloneCredentialFallback") < body.index("SecItemCopyMatching"),
                "committed fallback must take precedence over stale Keychain reads in " + start)

    require("static func resetLocalData()" in app, "credential reset entry point missing")
    require("ProviderKeychainHelper.clearCloneCredentialFallbackDirectory()" in app,
            "MAX reset misses protected fallback files")
    require('service.hasPrefix(cloneBundleID + ".")' in app,
            "reset is not restricted to the MAX Keychain namespace")
    require('for name in ["Documents", "Library", "tmp"]' not in app,
            "reset still deletes broad app directories")
    require("removePersistentDomain(forName: cloneBundleID)" not in app,
            "reset still removes unrelated MAX preferences")
    require("Other MAX app data is preserved" in reset_ui and
            "App Store Minis app is not affected" in reset_ui and
            "Clear MAX Credentials" in reset_ui,
            "reset UI does not accurately describe credential-only cleanup")

    for path in [
        "src/ios/Providers/Anthropic/OAuth/ClaudeOAuthManager.swift",
        "src/ios/Providers/OpenAI/OAuth/CodexOAuthManager.swift",
        "src/ios/Providers/Gemini/OAuth/GeminiOAuthManager.swift",
        "src/ios/Providers/Antigravity/OAuth/AntigravityOAuthManager.swift",
        "src/ios/Providers/Kimi/OAuth/KimiOAuthManager.swift",
        "src/ios/Providers/Copilot/OAuth/CopilotOAuthManager.swift",
        "src/ios/Providers/xAI/OAuth/XAIOAuthManager.swift",
    ]:
        source = (root / path).read_text(encoding="utf-8")
        require("guard ProviderKeychainHelper.saveOAuthToken" in source,
                "OAuth login completion ignores persistence failure: " + path)
    require("guard ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: instanceId)" in openrouter,
            "OpenRouter login completion ignores persistence failure")
    require("if !trimmedKey.isEmpty && !ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id)" in add,
            "manual API-key provider creation ignores persistence failure")
    require('guard ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token")' in add,
            "manual OAuth provider creation ignores persistence failure")
    require("guard ProviderKeychainHelper.saveAPIKey(key, instanceId: instance.id)" in collection,
            "provider collection creation ignores persistence failure")
    require("guard ProviderKeychainHelper.saveAPIKey(resolved, instanceId: id)" in collection,
            "provider collection field write ignores persistence failure")
    require('guard ProviderKeychainHelper.saveOAuthString(cleaned, instanceId: instanceId, account: "manual-oauth-token")' in detail,
            "provider detail manual-token save ignores persistence failure")
    require("guard ProviderKeychainHelper.saveOAuthToken(refreshed, instanceId: instanceId)" in
            (root / "src/ios/Providers/Gemini/OAuth/GeminiOAuthManager.swift").read_text(encoding="utf-8"),
            "Gemini token refresh ignores persistence failure")
    require("guard ProviderKeychainHelper.saveOAuthToken(refreshed, instanceId: instanceId)" in
            (root / "src/ios/Providers/Antigravity/OAuth/AntigravityOAuthManager.swift").read_text(encoding="utf-8"),
            "Antigravity token refresh ignores persistence failure")
    require("if ProviderKeychainHelper.saveAPIKey(value, instanceId: p.instanceId) { wrote = true }" in backup,
            "backup API-key import ignores persistence result")
    require("if ProviderKeychainHelper.saveRawOAuthToken(raw, instanceId: p.instanceId) { wrote = true }" in backup,
            "backup raw OAuth import ignores persistence result")
    require("skip original-app legacy Keychain migration in isolated MAX clone" in migration,
            "MAX migration may import credentials from the original app")
    print("PASS R4: hashed, protected fallback; stale-copy prevention; Bool save results")
    print("PASS R4: OAuth login/refresh, manual entry, provider tools and backup import are gated")
    print("PASS R4: credential-only reset preserves MAX app data and original Minis isolation")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 test_patch_clone_identity_r4.py /path/to/pinned/OpenMinis")
    main(Path(sys.argv[1]).resolve())
