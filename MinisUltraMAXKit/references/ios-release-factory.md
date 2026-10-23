# Build and signing engineer

Activation: use when the development task concerns ios release factory. Read only this specialist reference when relevant.

Prefer the local factory for Theos packages: minis-deb auto --project PATH --arch auto. It checks GNU make, clang, ldid, dpkg-deb, Perl, Bash, Theos and an iPhoneOS SDK; it installs supported host dependencies when possible, clones Theos into its managed cache if absent, and links an already-installed Xcode SDK when available. It must not silently download or accept Apple SDK license terms. Preserve explicit project ARCHS, THEOS_PACKAGE_SCHEME and signing flags; default to Theos ldid -S only when the project does not define signing. Build with FINALPACKAGE=1, verify package control metadata and payload, inspect each Mach-O slice for expected architectures and LC_CODE_SIGNATURE presence, and write BUILD_REPORT.json plus SHA256SUMS.txt. Do not install the DEB automatically. If local host execution or SDK requirements cannot be met, report NO-GO and use an authorized external build workflow rather than claiming a local build succeeded. Reuse user's existing private macOS/Xcode, RootHide Theos, SDK and Actions environment. Maintain reproducible toolchain revisions, dependency hashes and unmodified baselines. For IPA verify bundle IDs of main app and extensions, minimum OS, capabilities, entitlements, signing team and install data preservation. Never label unsigned build-only archives installable.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
