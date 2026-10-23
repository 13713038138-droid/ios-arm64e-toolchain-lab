# Web and cloud architecture

Activation: use when the development task concerns web cloud backend. Read only this specialist reference when relevant.

Design APIs with explicit auth, rate limits, retries, idempotency, structured errors and version compatibility. Consider local-offline constraints and cache invalidation. Verify observability, connection errors, pagination and secret storage. Test deployment separately from implementation, and provide a reversible rollout plan.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
