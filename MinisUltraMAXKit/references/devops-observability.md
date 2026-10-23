# Build and infrastructure reliability

Activation: use when the development task concerns devops observability. Read only this specialist reference when relevant.

Maintain pinned dependencies, reproducible build scripts, fail-closed CI, artifact hashes and exact action run/job links. Distinguish pending/queued/in-progress/failed and inspect the first causal compiler failure. Provide logs and a single minimal fix, not guesses. Do not expose credentials or publish private source while debugging CI.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
