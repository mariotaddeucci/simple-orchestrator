# CLAUDE.md — `simple-orchestrator-worker` (queue runner + vendors)

Scope: `packages/simple-orchestrator-worker/`.

## Why it exists

- Run the queue (dequeue/dispatch) with controlled parallelism.
- Implement vendors (Claude Code, OpenCode, GitHub Copilot) and the session lifecycle.
- Run the event scheduler loop that fires due events and updates `next_run`.

## Main goal

- Robust execution: concurrency, `workdir` serialization, cancellation, timeouts, and logs.

## Development guidelines

- Vendor-specific code lives in `vendors/`; do not spread vendor details into the runner.
- Integration with WebAPI (heartbeat, dequeue) must keep `core` shapes.
- Integration tests that depend on real vendor auth must be marked/auto-skipped in CI.

## Quick validation

```bash
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
