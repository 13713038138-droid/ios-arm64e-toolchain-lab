# iOS arm64e Toolchain Lab

Public **toolchain-only** diagnostics for the standard macOS GitHub Actions runner.

## What this repository contains
- Public instructions and a harmless, synthetic arm64e compile probe.
- Compiler availability and output-format checks for `swiftc`, Apple Clang, `arm64e`, and pointer authentication.

## What it must never contain
- Stheno or third-party plugin source, binaries, proprietary SDK archives, passwords, SSH keys, tokens, app identifiers, crash logs, or private material.
- Automated checkout, git clone, artifacts, or credentials from another repository.

A green workflow only verifies the public build runner. It does **not** prove a RootHide/Theos DEB can be built, that PAC ABI is correct for a particular private target, or that a one-piece keyboard layout works on a device.

The user's two Stheno repositories remain separate and private.
