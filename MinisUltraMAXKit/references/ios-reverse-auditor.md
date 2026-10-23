# Binary provenance and reverse engineering

Activation: use when the development task concerns ios reverse auditor. Read only this specialist reference when relevant.

Record binary hash, arm64e slice, load address, UUID and symbol relocation for every offset. Disassemble caller and callee, including branch-and-link and PAC transitions. Infer Objective-C, Swift and C calling conventions only from concrete evidence. Keep speculation separate. Map source line->machine instruction->runtime stack->observed effect and add a falsifying test.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
