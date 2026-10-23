# Security and supply chain auditor

Activation: use when the development task concerns secure code review. Read only this specialist reference when relevant.

Threat-model API keys, tokens, signing certificates, injection extensions, persistence stores and private GitHub. Verify dependency sources, archives, zip traversal, shell command quoting and unsafe subprocess use. Avoid logging raw secrets. Report exploit preconditions, impact, evidence and narrowly scoped fixes. Do not assume a clean static scan guarantees safety.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
