# Minis Dev Ultra MAX: local DEB factory

The local-first DEB factory is bundled into the R5 app overlay. Its entry point is the `minis-deb` command; the DevDEB slash command asks the agent to locate the active Theos project and invoke it.

## Commands

- minis-deb doctor — read-only report of host architecture, GNU make, clang, ldid, dpkg-deb, Perl, Bash, Theos and iPhoneOS SDK.
- minis-deb bootstrap — prepare supported host dependencies and clone Theos into the tool's managed cache when missing.
- minis-deb auto --project /path/to/project --arch auto — prepare what can be prepared, run a FINALPACKAGE=1 build, verify the resulting DEB and write evidence.
- minis-deb verify /path/to/package.deb — independently inspect a previously built package.
- minis-deb auto --project /path/to/project --arch arm64,arm64e — explicitly request both architectures.
- minis-deb auto --project /path/to/project --scheme roothide — explicitly select the RootHide scheme when the project does not already define it.

## Automatic behavior

1. Reuse the project’s own Makefile, ARCHS, package scheme and signing flags instead of overriding explicit configuration.
2. Install missing host dependencies through apk, apt-get or Homebrew when available and authorized by the current environment.
3. Reuse an installed Theos and iPhoneOS SDK. If Theos is missing, clone it into ~/.cache/minis-dev-ultra/theos. On macOS, link the already-installed Xcode iPhoneOS SDK when needed.
4. Run Theos with FINALPACKAGE=1. When the project does not define a signing command, use TARGET_CODESIGN=ldid and TARGET_CODESIGN_FLAGS=-S.
5. Require a fresh .deb output, inspect Package/Version/Architecture, extract and inspect Mach-O slices, require requested architecture slices, and check that each Mach-O slice has an LC_CODE_SIGNATURE command.
6. Write the DEB, BUILD_REPORT.json, SHA256SUMS.txt and minis-deb-build.log into the selected output directory.

## Safety and limits

- The factory does not install the DEB on a device. Build success is not device compatibility approval.
- LC_CODE_SIGNATURE presence verifies the signature structure is present; it is not an Apple Developer signature, notarization, or a substitute for device testing.
- The factory does not silently download Apple SDKs or accept Apple SDK license terms. It reuses an existing Theos SDK or an already-installed Xcode SDK.
- If the current host cannot execute its compiler/linker, has no usable iPhoneOS SDK, lacks signing tools, or cannot install dependencies without required privileges, it returns NO-GO with the missing capability. It must not claim that an IPA, DEB, signature or build environment is ready when it is not.
- The package output and logs are kept for audit and rollback; known-good project source and existing packages are not deleted.
