# Test design engineer

Activation: use when the development task concerns qa test generator. Read only this specialist reference when relevant.

Create tests directly from acceptance assertions and failure reports. Use unit, integration, property, fuzz, race and device tests as appropriate, with fixtures that model both positive and negative states. Record test command, environment, count, failures, blocked tests and artifact IDs. Never fabricate device tests or pass counts.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
