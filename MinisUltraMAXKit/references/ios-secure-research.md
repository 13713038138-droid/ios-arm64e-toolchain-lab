# Secure toolchain and platform research

Activation: use when the development task concerns ios secure research. Read only this specialist reference when relevant.

Prefer local repository and binary evidence. Research upstream changes only when relevant to exact implementation. Cross-check API availability by iOS deployment target and original Xcode headers. Do not expose private repositories, accounts, signing assets or app data to search or untrusted tools. Secrets findings display type and location only, never secret values.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
