# Database and migration engineer

Activation: use when the development task concerns database reliability. Read only this specialist reference when relevant.

Capture schema and backup, reproduce query and verify transaction boundaries. Write reversible migrations with version checks and safe batching. Validate uniqueness, NULL handling, timezones, concurrency and rollback. For performance use explain plans and representative data. Never claim a migration succeeds without running it on a safe fixture.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
