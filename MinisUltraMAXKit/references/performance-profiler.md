# Performance and memory specialist

Activation: use when the development task concerns performance profiler. Read only this specialist reference when relevant.

Benchmark before optimizing and define frame, CPU, memory and energy budgets. Inspect call stacks, hot paths and per-frame allocations; isolate expensive SpringBoard display-link ticks from asynchronous events. Use realistic long sessions and test regression after changes. Do not claim a latency win based only on fewer lines of code.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.
