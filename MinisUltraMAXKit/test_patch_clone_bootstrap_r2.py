#!/usr/bin/env python3
from pathlib import Path
import tempfile, subprocess, sys

PIN = "b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c"

def check_repo(root: Path):
    req = (root/"src/ios/Agent/Chat/AIChatViewModel+RequestBudget.swift").read_text()
    app = (root/"src/ios/MinisApp.swift").read_text()
    pbx = (root/"src/ios/Minis.xcodeproj/project.pbxproj").read_text()
    assert 'Bundle.main.bundleIdentifier == "com.openminis.devultramax"' in req
    assert 'MinisMAXIsolatedGroup_R1' in req
    assert 'Bundle.main.bundleIdentifier != "com.openminis.devultramax"' in app
    assert 'PRODUCT_BUNDLE_IDENTIFIER = com.openminis.devultramax;' in pbx
    assert 'PRODUCT_BUNDLE_IDENTIFIER = com.openminis.app;' not in pbx
    print("R2_PATCH_ASSERTIONS_OK")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_patch_clone_bootstrap_r2.py <patched-upstream-root>")
    check_repo(Path(sys.argv[1]))
