# CLAUDE.md — `simple-orchestrator-worker` (queue + vendors)

Scope: `packages/simple-orchestrator-worker/`.

## Why it exists

- Run the queue (dequeue/dispatch) with controlled parallelism.
- Implement vendors (Claude Code, OpenCode, GitHub Copilot) and the session lifecycle.

## Main goal

Robust execution: concurrency, per-`workdir` serialization, cancellation, timeouts, and dual logging.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_worker/worker_runner.py` | `WorkerRunner` — dequeue/dispatch loop + heartbeat sender |
| `src/simple_orchestrator_worker/worker_service.py` | Service wrapper / startup helpers |
| `src/simple_orchestrator_worker/session_store.py` | Thin wrapper around the repository for saving/updating `SessionRecord` |
| `src/simple_orchestrator_worker/logging_config.py` | Dual loggers: internal (`orchestrator.log`) and vendor (`vendor.log`) |
| `src/simple_orchestrator_worker/vendors/base.py` | `BaseVendor` abstract class |
| `src/simple_orchestrator_worker/vendors/claude_code.py` | `ClaudeCodeVendor` |
| `src/simple_orchestrator_worker/vendors/opencode.py` | `OpenCodeVendor` |
| `src/simple_orchestrator_worker/vendors/github_copilot.py` | `GithubCopilotVendor` |

## WorkerRunner lifecycle

1. `start()` — launches heartbeat loop and dequeue/dispatch loop concurrently.
2. **Heartbeat loop** — sends `POST /heartbeat` every `heartbeat_interval_seconds`.
3. **Dispatch loop** — polls `dequeue_next()` every `poll_interval_seconds`; respects `max_active_sessions`.
4. `_run_lease()` — acquires per-`workdir` lock, then calls vendor `run()`.
5. `_process_lease()` — updates queue item with `session_id`, runs vendor, writes final status back.

## Vendor pattern (`BaseVendor`)

```python
run(config: SessionConfig, timeout_minutes: float, session_id: str) -> (session_id, final_status)
_run_session(session_id, config)   # abstract — vendor-specific blocking execution
_vendor_kill(session_id)           # abstract — best-effort termination
list_models() -> list[ModelInfo]
```

Vendor-specific code stays in `vendors/` — never spread vendor details into `worker_runner.py`.

## Concurrency rules

- `max_active_sessions` caps how many vendor sessions run in parallel.
- Sessions on the same `workdir` are serialized (one at a time per directory) to avoid conflicts.
- Cancellation is best-effort via `_vendor_kill(session_id)`.

## Testing

Integration tests that require real vendor authentication must be marked/auto-skipped in CI.

## Quick validation

```bash
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
