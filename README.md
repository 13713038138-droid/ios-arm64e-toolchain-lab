# iOS arm64e Toolchain Lab + Minis Dev Ultra MAX R5

Public macOS arm64e toolchain diagnostics and repeatable Minis R5 test builds.

## What this repository contains

- A synthetic arm64e compile probe for the standard macOS GitHub Actions runner.
- `MinisUltraMAXKit/`: the public Minis R5 development helpers, specialist references, runtime wrappers, and regression tests.
- A GitHub Actions workflow that checks out the pinned upstream OpenMinis revision, applies the R5 enhancements, runs tests, builds an isolated iOS test app, and publishes the resulting test IPA and evidence to Releases.

## Privacy and safety boundaries

- Only the Minis R5 helper kit is published here. The original Stheno source repositories remain separate and private; their source trees and archives are not copied into this repository.
- Private repository identifiers and R32-specific default paths were replaced with generic placeholders in the public helper copy.
- This repository must not contain access tokens, passwords, SSH keys, private signing certificates, proprietary SDK archives, or private Stheno source/binaries.
- The R5 IPA is an isolated, ad-hoc-signed TrollStore test build, not an Apple Developer-signed App Store replacement. Keep the original Minis app and its data installed.

A successful toolchain probe alone does not prove that the iOS project compiles. Only a successful R5 workflow and its attached evidence establish that a candidate IPA was produced.
