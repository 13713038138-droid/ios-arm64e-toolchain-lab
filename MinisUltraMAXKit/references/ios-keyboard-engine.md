# iOS keyboard and scene engineer

Activation: use when the development task concerns ios keyboard engine. Read only this specialist reference when relevant.

Distinguish system keyboard host, scene owner, card geometry writer, animation transaction and saved model frame. State machine: hidden->showing->visible->hiding->hidden, including orientation changes, cold launch, external keyboard and failed restore. Save original size once per session; reject writing expanded bounds back as baseline. Show and Hide must each have positive and negative controls.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
