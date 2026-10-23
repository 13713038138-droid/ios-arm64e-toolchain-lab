#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
BUNDLE = "com.openminis.devultramax"
PIN = "b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c"

def must(path):
    p = ROOT / path
    if not p.exists():
        raise SystemExit(f"missing: {path}")
    return p

def replace_once(text, old, new, label):
    n = text.count(old)
    if n < 1:
        raise SystemExit(f"pattern not found for {label}")
    return text.replace(old, new)

# 1) Isolate bundle identifiers without touching upstream source repo.
pbx = must("src/ios/Minis.xcodeproj/project.pbxproj")
s = pbx.read_text()
repls = {
    "PRODUCT_BUNDLE_IDENTIFIER = com.openminis.app;":
        f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE};",
    "PRODUCT_BUNDLE_IDENTIFIER = com.openminis.app.ShareExtension;":
        f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE}.ShareExtension;",
    "PRODUCT_BUNDLE_IDENTIFIER = com.openminis.app.FileProvider;":
        f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE}.FileProvider;",
    "PRODUCT_BUNDLE_IDENTIFIER = com.openminis.app.AgentWidget;":
        f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE}.AgentWidget;",
}
for old, new in repls.items():
    if old in s:
        s = s.replace(old, new)
pbx.write_text(s)

# 2) Native local-sandbox fallback for the two force-unwrapped App Group roots.
req = must("src/ios/Agent/Chat/AIChatViewModel+RequestBudget.swift")
s = req.read_text()
old_root = '''    nonisolated static var minisAppGroupRoot: URL {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        )!.appendingPathComponent("MinisFileProvider", isDirectory: true)
    }'''
new_root = '''    nonisolated static var minisAppGroupRoot: URL {
        let fm = FileManager.default
        if Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
            let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first!
            let base = library.appendingPathComponent("MinisMAXIsolatedGroup_R1", isDirectory: true)
            let url = base.appendingPathComponent("MinisFileProvider", isDirectory: true)
            try? fm.createDirectory(at: url, withIntermediateDirectories: true)
            return url
        }
        return fm.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        )!.appendingPathComponent("MinisFileProvider", isDirectory: true)
    }'''
old_cfg = '''    nonisolated static var minisConfigRoot: URL {
        let url = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
        )!.appendingPathComponent("MinisConfig", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }'''
new_cfg = '''    nonisolated static var minisConfigRoot: URL {
        let fm = FileManager.default
        let url: URL
        if Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
            let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first!
            url = library
                .appendingPathComponent("MinisMAXIsolatedGroup_R1", isDirectory: true)
                .appendingPathComponent("MinisConfig", isDirectory: true)
        } else {
            url = fm.containerURL(
                forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID
            )!.appendingPathComponent("MinisConfig", isDirectory: true)
        }
        try? fm.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }'''
s = replace_once(s, old_root, new_root, "minisAppGroupRoot")
s = replace_once(s, old_cfg, new_cfg, "minisConfigRoot")
req.write_text(s)

# 3) Do not register FileProvider or migrate legacy group data in the isolated build.
app = must("src/ios/MinisApp.swift")
s = app.read_text()
old = '''                    // Register FileProvider domain for shared files
                    Self.registerFileProviderDomain()
                    // Migrate legacy shared dir to App Group container
                    Self.migrateSharedDirToAppGroup()
                    // Trace the resolved AppGroup paths so we can confirm the'''
new = '''                    if Bundle.main.bundleIdentifier != "com.openminis.devultramax" {
                        // Native upstream behavior for the official build.
                        Self.registerFileProviderDomain()
                        Self.migrateSharedDirToAppGroup()
                    } else {
                        lifecycleLog.info("[MinisMAX R2] isolated local-container mode; FileProvider registration and legacy App Group migration disabled")
                    }
                    // Trace the resolved AppGroup paths so we can confirm the'''
s = replace_once(s, old, new, "FileProvider launch gate")
app.write_text(s)

# 4) R2.1: TrollStore/isolated builds may reject synchronizable Keychain writes.
# Upstream already reads sync first and local/legacy second, but its write path
# deletes both and only attempts the sync write. If that SecItemAdd fails, OAuth
# appears successful in the browser but the app immediately has no token.
store = must("src/ios/Providers/ProviderConfigStore.swift")
s = store.read_text()

sync_add = '''        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)'''
fallback_add = '''        var addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        if addStatus != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
            // MinisMAX R2.1: preserve credentials locally when the isolated
            // TrollStore signature cannot use synchronizable Keychain.
            addQuery.removeValue(forKey: kSecAttrSynchronizable as String)
            addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        }'''
count = s.count(sync_add)
if count < 3:
    raise SystemExit(f"expected >=3 synchronizable Keychain add sites, found {count}")
s = s.replace(sync_add, fallback_add)

raw_add = '''        let status = SecItemAdd(addQuery as CFDictionary, nil)
        if status != errSecSuccess {
            AppLogger(category: "Keychain").warning("write rawOAuthToken instanceId=\\(instanceId.prefix(8)) status=\\(status)")
        }'''
raw_fallback = '''        var status = SecItemAdd(addQuery as CFDictionary, nil)
        if status != errSecSuccess && Bundle.main.bundleIdentifier == "com.openminis.devultramax" {
            addQuery.removeValue(forKey: kSecAttrSynchronizable as String)
            status = SecItemAdd(addQuery as CFDictionary, nil)
        }
        if status != errSecSuccess {
            AppLogger(category: "Keychain").warning("write rawOAuthToken instanceId=\\(instanceId.prefix(8)) status=\\(status)")
        }'''
s = replace_once(s, raw_add, raw_fallback, "raw OAuth Keychain fallback")
store.write_text(s)

print("R2_NATIVE_PATCH_OK")

