# R5: automatic development requirement routing

R5 adds a deterministic, offline router to `devctl.py route --task "..." [--path PATH ...]`.
It scores specialist profiles from the requirement text and supplied file extensions, then emits JSON containing a primary profile, supporting profiles, selected specialist references, recommended local tools, risk level, confidence, and required validation gates.

Profiles cover iOS binary/reverse engineering, iOS build/packaging, Swift/UIKit, Python runtime, on-device IDE/workspace, compiler/SDK lifecycle, terminal sessions, install/runtime diagnostics, agent approval, project templates, Git/transfer credentials, disassembly extensions, frontend, backend/API/data, crash/ownership triage, performance/token efficiency, security/isolation, and CI/release testing. Mixed tasks combine up to four near-top profiles; unknown tasks fall back to general engineering. The router does not read project files or execute changes by itself: the skill uses its output to choose the workflow, then inspects actual source evidence.

## Runtime tools

- `minis-dev-ultra route --task "..." --path path/to/file.swift`: select a development workflow.
- `minis-bin path/to/app.ipa`: static IPA, Mach-O, universal-slice, and DEB-header inspection through the existing stdlib-only inspector.
- `minis-tk ...`: existing token/log analysis.

All three wrappers share `ensure-python3.sh`. In Alpine/iSH they use an existing Python 3 runtime when present; otherwise they attempt `apk add --quiet python3` and fail closed with a log location if installation is unavailable. No pip dependencies are needed for the bundled tools. This is lazy provisioning, not a claim that Python is preinstalled in every guest before first use.

## Apelin feature-parity work

Reference: https://github.com/owngoal-dev/Apelin, MIT-licensed release commit 3345f243a0cf979fc44f5cc2b6c0230f12ac141b (0.1.5).

R5 now adds explicit routing profiles for on-device IDE/workspace, compiler and SDK lifecycle, persistent terminal sessions, install diagnostics, agent approval, project templates, Git/transfer credentials and optional disassembly extensions. The safe scaffolder generates Theos tweak, UIKit app, CLI and preference-bundle starters. The new command scaffolds a Theos tweak, UIKit app, CLI or preference bundle at a new path and refuses to overwrite existing files:

    minis-dev-ultra new --kind tweak|app|cli|preferences --name Name --bundle-id com.example.name --path ./Name --scheme roothide|rootless

The scaffold does not install packages. Run minis-deb doctor, review the generated files, then minis-deb auto --project PATH --arch auto and inspect the package report and hash.

This is a first parity slice, not full Apelin parity. A native editor UI, on-device Apple CLT/iPhoneOS SDK manager, daemon-backed persistent terminal/jobs, authenticated privileged install IPC, post-respring load watcher, crash symbolication/UI tree/actions, transfer manager and Capstone/Keystone extensions remain unported. Do not claim those features exist until implemented and device-tested.

## Safety and acceptance

- Routing is deterministic and inspectable; no model-switching or quota-bypass claims.
- Static binary parsing is read-only and bounded; malformed universal-slice offsets are rejected.
- R5 uses a separate `com.openminis.devultramax.r5` identity and `group.com.openminis.devultramax.r5` namespace so the R4 test clone remains a rollback baseline.
- CI must pass Python compile, unit tests, shell wrapper tests, patch source guards, Xcode build, isolated ad-hoc signature verification, artifact checksum and provenance.
- CI success is not device validation. R5 must be installed/tested separately in TrollStore before being considered accepted.
