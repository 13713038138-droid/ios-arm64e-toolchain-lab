#!/usr/bin/env python3
"""Static release gates for the R3 clone-only persistence patch."""
from pathlib import Path
import plistlib
import sys

CLONE = "com.openminis.devultramax"

def require(condition, message):
    if not condition:
        raise SystemExit("NO-GO: " + message)

def main(root: Path):
    store = (root / "src/ios/Providers/ProviderConfigStore.swift").read_text()
    require("private static func providerService(instanceId: String) -> String" in store,
            "provider Keychain service helper missing")
    require('return "com.openminis.devultramax.provider.\\(instanceId)"' in store,
            "clone Keychain namespace missing")
    require('return "com.openminis.app.provider.\\(instanceId)"' in store,
            "original app Keychain namespace not preserved")
    require('let service = "com.openminis.app.provider.\\(instanceId)"' not in store,
            "provider operation still hardcodes the original Keychain namespace")
    require(store.count('if Bundle.main.bundleIdentifier != "com.openminis.devultramax"') >= 4,
            "clone-local-only Keychain writes not applied")
    require("@discardableResult\n    static func saveOAuthToken<T: Codable>" in store and "-> Bool {" in store,
            "OAuth persistence result not exposed")
    for path in [
        "src/ios/Providers/Anthropic/OAuth/ClaudeOAuthManager.swift",
        "src/ios/Providers/OpenAI/OAuth/CodexOAuthManager.swift",
        "src/ios/Providers/Gemini/OAuth/GeminiOAuthManager.swift",
        "src/ios/Providers/Antigravity/OAuth/AntigravityOAuthManager.swift",
        "src/ios/Providers/Kimi/OAuth/KimiOAuthManager.swift",
        "src/ios/Providers/Copilot/OAuth/CopilotOAuthManager.swift",
        "src/ios/Providers/xAI/OAuth/XAIOAuthManager.swift",
    ]:
        source = (root / path).read_text()
        require("guard ProviderKeychainHelper.saveOAuthToken" in source,
                f"login success is not gated on Keychain persistence: {path}")

    require("cloneCredentialFallbackURL(service: String, account: String) -> URL?" in store,
            "MAX protected credential fallback path helper missing")
    require("FileProtectionType.completeUntilFirstUserAuthentication" in store,
            "MAX fallback credentials are not protected by iOS data protection")
    require("private static func writeCloneCredentialFallback(_ data: Data, service: String, account: String) -> Bool" in store,
            "MAX protected credential fallback writer missing")
    require("private static func readCloneCredentialFallback(service: String, account: String) -> Data?" in store,
            "MAX protected credential fallback reader missing")
    require('protectedFallbackSaved=\\(fallbackSaved)' in store,
            "credential write logs do not disclose fallback result")
    require("src=protectedFallback" in store,
            "credential reads do not report protected fallback source")
    require("deleteCloneCredentialFallback(service: service, account: acct)" in store,
            "OAuth token deletion does not clear MAX fallback credentials")
    require("deleteCloneCredentialFallback(service: service, account: account)" in store,
            "OAuth metadata deletion does not clear MAX fallback credentials")
    migration = (root / "src/ios/Providers/ProviderMigration.swift").read_text()
    require('if Bundle.main.bundleIdentifier == "com.openminis.devultramax"' in migration,
            "clone still runs original-app legacy credential migration")

    for path, old, clone in [
        ("src/ios/Agent/Session/MCPOAuthController.swift", "com.openminis.app.mcp-oauth", "com.openminis.devultramax.mcp-oauth"),
        ("src/ios/Shared/EnvVarStore.swift", "com.openminis.app.envvar", "com.openminis.devultramax.envvar"),
        ("src/ios/Agent/Backup/Remote/RcloneRemoteStore.swift", "com.openminis.app.rclone", "com.openminis.devultramax.rclone"),
        ("src/ios/Shared/DeviceIdentity.swift", "com.openminis.app.device", "com.openminis.devultramax.device"),
    ]:
        source = (root / path).read_text()
        require(old in source and clone in source, f"Keychain service isolation missing: {path}")

    cloud = (root / "src/ios/Agent/Sync/CloudSyncEngine.swift").read_text()
    require(cloud.count('Bundle.main.bundleIdentifier != "com.openminis.devultramax"') >= 3,
            "clone CloudKit engine guards missing")
    v2 = (root / "src/ios/Agent/Sync/V2/SyncV2Bootstrap.swift").read_text()
    require('Bundle.main.bundleIdentifier != "com.openminis.devultramax"' in v2,
            "clone SyncCore startup guard missing")

    app = (root / "src/ios/MinisApp.swift").read_text()
    require("MinisMAXDataIsolation.bootstrap()" in app, "reinstall marker bootstrap missing")
    require("static func resetLocalData()" in app, "MAX local data reset implementation missing")
    require('service.hasPrefix(cloneBundleID + ".")' in app,
            "Keychain cleanup is not restricted to the clone namespace")

    with (root / "src/ios/Info.plist").open("rb") as f:
        info = plistlib.load(f)
    schemes = [scheme for entry in info.get("CFBundleURLTypes", [])
               for scheme in entry.get("CFBundleURLSchemes", [])]
    require(CLONE in schemes, "clone OAuth URL scheme missing")
    require("com.openminis.app" not in schemes, "original callback scheme still claimed by clone")
    require("UTImportedTypeDeclarations" in info, "backup UTI should be imported by clone")
    require("UTExportedTypeDeclarations" not in info, "clone still claims ownership of original backup UTI")

    picker = (root / "src/ios/Views/Settings/BackupRestoreView.swift").read_text()
    require("? [.item]" in picker, "clone backup picker is not broad enough for Files-provider items")
    restore = (root / "src/ios/Views/Settings/BackupAndRestoreView.swift").read_text()
    require("Clear MAX Data" in restore and "MinisMAXDataIsolation.resetLocalData()" in restore,
            "user-confirmed MAX-only data reset UI missing")

    print("PASS: unique MAX Keychain namespaces and local-only credential writes")
    print("PASS: OAuth login reports Keychain persistence failure instead of false success")
    print("PASS: original legacy credentials and iCloud sync are isolated from MAX")
    print("PASS: reinstall cleanup only deletes com.openminis.devultramax.* Keychain items")
    print("PASS: explicit MAX-only data reset and broad validated backup picker")
    print("PASS: clone OAuth scheme and imported backup UTI")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_patch_clone_identity_r3.py <patched-upstream-root>")
    main(Path(sys.argv[1]).resolve())
