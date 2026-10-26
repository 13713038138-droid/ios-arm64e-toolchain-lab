#!/usr/bin/env python3
"""IPS 2C490985 regression gate for isolated test clone. Run after patch_ips_sigtrap.py."""
from pathlib import Path
import os
import sys

if len(sys.argv)!=2: raise SystemExit("usage: python3 test_ips_sigtrap.py <patched OpenMinis repo>")
base=Path(sys.argv[1])/"src/ios"
bundle_id = os.environ.get("MINIS_MAX_BUNDLE_ID", "com.openminis.devultramax")
if bundle_id not in ("com.openminis.devultramax", "com.openminis.devultramax.r5", "com.openminis.devultramax.r54", "com.openminis.devultramax.r55", "com.openminis.devultramax.r56", "com.openminis.devultramax.r57", "com.openminis.devultramax.r58", "com.openminis.devultramax.r59", "com.openminis.devultramax.r60", "com.openminis.devultramax.r61"):
    raise SystemExit("NO-GO: unsupported isolated test bundle identity")
checks=[
 ("Agent/Chat/AIChatViewModel+RequestBudget.swift","minisIsolatedContainerBase"),
 ("Agent/Chat/AIChatViewModel+RequestBudget.swift","Library/MinisDevUltraIsolated"),
 ("Agent/Chat/AIChatViewModel+RequestBudget.swift","minisIsolatedContainerBase.appendingPathComponent("),
 ("MinisApp.swift","FileProvider registration skipped"),
 ("MinisApp.swift","skipping App Group migration"),
 ("FileProvider/FileProviderExtension.swift","Library/MinisDevUltraExtensionIsolated"),
 ("Shared/SharedContainerStore.swift","group." + bundle_id),
 ("Minis.entitlements","group." + bundle_id),
 ("Minis.entitlements","iCloud." + bundle_id),
]
for path,word in checks:
    s=(base/path).read_text(encoding="utf-8")
    assert word in s, "NO-GO: missing "+path+" "+word
for p in base.rglob("*"):
    if p.suffix not in (".swift",".entitlements",".plist") or not p.is_file():continue
    s=p.read_text(encoding="utf-8")
    for forbidden in ("group.com.openminis.app","iCloud.com.openminis.app","com.openminis.app.files"):
        assert forbidden not in s, f"NO-GO original app identity in {p}: {forbidden}"
request=(base/"Agent/Chat/AIChatViewModel+RequestBudget.swift").read_text()
assert ')!.appendingPathComponent("MinisFileProvider"' not in request
assert ')!.appendingPathComponent("MinisConfig"' not in request
store=(base/"Providers/ProviderConfigStore.swift").read_text(encoding="utf-8")
assert "com.openminis.app.provider." not in store, "NO-GO: original provider Keychain namespace remains"
assert store.count(bundle_id + ".provider.") >= 11, "NO-GO: MAX provider namespace incomplete"
assert 'addQuery[kSecAttrSynchronizable as String] = true' not in store, "NO-GO: MAX still writes synchronizable credentials"
assert 'addQuery[kSecAttrSynchronizable as String] != nil' not in store, "NO-GO: fallback is still gated on a sync attribute"
assert "fallbackAttempted = true" not in store and "localQuery[kSecValueData as String]" not in store, "NO-GO: obsolete Keychain-only fallback remains"
for marker in [
    "MinisMAXCredentialFallback",
    "FileProtectionType.completeUntilFirstUserAuthentication",
    "isExcludedFromBackup = true",
    "SHA256.hash(data: key)",
    "protectedFallbackSaved=",
    "writeCloneCredentialFallback",
    "readCloneCredentialFallback",
    "deleteCloneCredentialFallback",
]:
    assert marker in store, "NO-GO: missing credential fallback invariant " + marker
for path in [
    "Providers/Anthropic/OAuth/ClaudeOAuthManager.swift",
    "Providers/OpenAI/OAuth/CodexOAuthManager.swift",
    "Providers/Gemini/OAuth/GeminiOAuthManager.swift",
    "Providers/Antigravity/OAuth/AntigravityOAuthManager.swift",
    "Providers/Kimi/OAuth/KimiOAuthManager.swift",
    "Providers/Copilot/OAuth/CopilotOAuthManager.swift",
    "Providers/xAI/OAuth/XAIOAuthManager.swift",
]:
    assert "guard ProviderKeychainHelper.saveOAuthToken" in (base/path).read_text(encoding="utf-8"), "NO-GO: OAuth login not gated on persistence: " + path
app = (base/"MinisApp.swift").read_text(encoding="utf-8")
assert "static func resetLocalData()" in app, "NO-GO: MAX-only reset helper missing"
assert "ProviderKeychainHelper.clearCloneCredentialFallbackDirectory()" in app, "NO-GO: MAX reset misses protected fallback files"
assert 'service.hasPrefix(cloneBundleID + ".")' in app, "NO-GO: reset cleanup is not namespace-limited"
reset_ui = (base/"Views/Settings/BackupAndRestoreView.swift").read_text(encoding="utf-8")
assert "Clear MAX Credentials" in reset_ui and "MinisMAXDataIsolation.resetLocalData()" in reset_ui, "NO-GO: MAX-only credential reset UI missing"
assert "Other MAX app data is preserved" in reset_ui and "App Store Minis app is not affected" in reset_ui, "NO-GO: credential-reset scope warning missing"
assert "FileManager.default.setAttributes(" in store, "NO-GO: fallback directory protection not enforced for existing directories"
assert store.count("fallbackSavedBeforeKeychain =") == 4, "NO-GO: credential writers must stage fallback before deleting old Keychain items"
assert "stageCloneCredentialFallback" in store and "keychainStatus != errSecItemNotFound" in store, "NO-GO: preflight must preserve existing Keychain/fallback credentials before destructive writes"
assert "try? FileManager.default.removeItem(at: url)" not in store, "NO-GO: fallback write failure must not delete the previously committed credential"
assert "replaceItemAt(url, withItemAt: temporaryURL)" in store and "removeItem(at: temporaryURL)" in store, "NO-GO: fallback replacement must commit atomically through a protected temporary file"
assert "try directory.setResourceValues(values)" in store and "try temporaryURL.setResourceValues(values)" in store, "NO-GO: protected credential fallback must fail closed if backup exclusion fails"
assert 'var directory = support.appendingPathComponent("MinisMAXCredentialFallback", isDirectory: true)' in store, "NO-GO: fallback directory URL must be mutable for resource protection"
assert 'var temporaryURL = directory.appendingPathComponent(UUID().uuidString + ".credential.tmp", isDirectory: false)' in store, "NO-GO: fallback temporary URL must be mutable for backup exclusion"
assert "return addStatus == errSecSuccess || fallbackSaved" in store, "NO-GO: API-key persistence result not returned"
assert "return status == errSecSuccess || fallbackSaved" in store, "NO-GO: raw OAuth persistence result not returned"
assert "return keychainStatus == errSecSuccess || fallbackSaved" in store, "NO-GO: OAuth-string persistence result not returned"
assert "static func saveAPIKey(_ key: String, instanceId: String, caller: String = #function) -> Bool {" in store, "NO-GO: API-key save result signature missing"
assert "static func saveRawOAuthToken(_ data: Data, instanceId: String) -> Bool {" in store, "NO-GO: raw OAuth save result signature missing"
assert "static func saveOAuthToken<T: Codable>(_ token: T, instanceId: String, caller: String = #function) -> Bool {" in store, "NO-GO: typed OAuth save result signature missing"
assert "static func saveOAuthString(_ value: String, instanceId: String, account: String, caller: String = #function) -> Bool {" in store, "NO-GO: OAuth-string save result signature missing"
assert "write oauthString aborted: cannot safely stage existing credential" in store and "return false" in store[store.index("write oauthString aborted: cannot safely stage existing credential") - 220:store.index("write oauthString aborted: cannot safely stage existing credential") + 260], "NO-GO: OAuth-string writer must preserve the last valid credential if staging fails"
for start, end in [
    ("static func loadAPIKey", "static func deleteAPIKey"),
    ("static func loadRawOAuthToken", "@discardableResult\n    static func saveOAuthToken"),
    ("static func loadOAuthToken<T: Codable>", "static func deleteOAuthToken"),
    ("static func loadOAuthString", "static func deleteOAuthString"),
]:
    begin = store.index(start)
    finish = store.index(end, begin + len(start))
    body = store[begin:finish]
    assert "readCloneCredentialFallback" in body and body.index("readCloneCredentialFallback") < body.index("SecItemCopyMatching"), "NO-GO: committed fallback must outrank stale Keychain reads in " + start
assert 'for name in ["Documents", "Library", "tmp"]' not in app, "NO-GO: reset still deletes broad app directories"
assert "removePersistentDomain(forName: cloneBundleID)" not in app, "NO-GO: reset removes unrelated MAX preferences"
openrouter=(base/"Providers/OpenRouter/OAuth/OpenRouterOAuthManager.swift").read_text(encoding="utf-8")
assert "guard ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: instanceId)" in openrouter, "NO-GO: OpenRouter OAuth success ignores persistence failure"
add_provider=(base/"Views/Providers/AddProviderView.swift").read_text(encoding="utf-8")
assert "if !trimmedKey.isEmpty && !ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id)" in add_provider, "NO-GO: manual API key flow ignores persistence failure"
assert 'guard ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token")' in add_provider, "NO-GO: manual OAuth token flow ignores persistence failure"
backup=(base/"Agent/Backup/BackupSecretsImporter.swift").read_text(encoding="utf-8")
assert "if ProviderKeychainHelper.saveAPIKey(value, instanceId: p.instanceId) { wrote = true }" in backup, "NO-GO: backup API key import ignores persistence failure"
assert "if ProviderKeychainHelper.saveRawOAuthToken(raw, instanceId: p.instanceId) { wrote = true }" in backup, "NO-GO: backup raw OAuth import ignores persistence failure"
assert 'if ProviderKeychainHelper.saveOAuthString(\n                    value, instanceId: p.instanceId, account: "manual-oauth-token") { wrote = true }' in backup, "NO-GO: backup manual OAuth import ignores persistence failure"
migration=(base/"Providers/ProviderMigration.swift").read_text(encoding="utf-8")
assert "if migrateOAuthTokens(store: store)" in migration and "return allPersisted" in migration, "NO-GO: OAuth migration must retry if persistence fails"
assert migration.count("guard ProviderKeychainHelper.saveOAuthToken(token, instanceId: instance.id) else") >= 3, "NO-GO: migration may delete legacy OAuth tokens before persistence succeeds"
assert "retaining legacy metadata" in migration, "NO-GO: failed metadata persistence may erase legacy state"
assert "if ProviderKeychainHelper.loadOAuthToken(instanceId: instance.id, as: GeminiTokenStorage.self) == nil" in migration, "NO-GO: Gemini metadata retry is skipped when the token already exists"
print("PASS: local-only Keychain + protected fallback + stale-copy prevention + scoped credential cleanup + login/import result gates")
