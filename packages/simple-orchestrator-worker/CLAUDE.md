# CLAUDE.md — `simple-orchestrator-worker` (queue + vendors)

Scope: `packages/simple-orchestrator-worker/`.

## Why it exists

- Run the queue (dequeue/dispatch) with controlled parallelism.
- Implement vendors (Claude Code, OpenCode, GitHub Copilot, Jules) and the session lifecycle.
- Run the event scheduler loop that fires due events and updates `next_run`.

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
| `src/simple_orchestrator_worker/vendors/jules.py` | `JulesVendor` |

## WorkerRunner lifecycle

`WorkerRunner.client` is typed as `IOrchestratorClient` (from `core`). It is satisfied by both `OrchestratorApiClient` (distributed mode) and `StandaloneClient` (standalone mode). Never type it as a concrete class.

`ApiSessionStore.client` is also typed as `IOrchestratorClient`. In standalone mode, use `StandaloneSessionStore` (backed by `OrchestratorDB`) instead.

1. `start()` — launches heartbeat loop, dequeue/dispatch loop, and event scheduler loop concurrently.
2. **Heartbeat loop** — calls `client.send_heartbeat()` every `heartbeat_interval_seconds`.
3. **Dispatch loop** — polls `client.dequeue_next()` every `poll_interval_seconds`; respects `max_active_sessions`.
4. **Event scheduler loop** — polls for due events via `client.list_events(enabled=True)`; enqueues them via `client.enqueue()` if no duplicate pending task exists; updates `next_run` via `client.update_event()`.
5. `_run_lease()` — acquires per-`workdir` lock, then calls vendor `run()`.
6. `_process_lease()` — updates queue item with `session_id`, runs vendor, writes final status back.

## Vendor pattern (`BaseVendor`)

```python
run(config: SessionConfig, timeout_minutes: float, session_id: str) -> (session_id, final_status)
execute_session(config: SessionConfig) -> AsyncIterator[Any]
prepare_and_execute(config: SessionConfig) -> AsyncIterator[Any]
_run_session(session_id, config)   # abstract — vendor-specific blocking execution
_vendor_kill(session_id)           # abstract — best-effort termination
list_models() -> list[ModelInfo]
```

Vendor-specific code stays in `vendors/` — never spread vendor details into `worker_runner.py`.

## Concurrency rules

- `always_open_pr` (default True) — if the workdir is a git worktree, the worker appends an instruction to open a PR at the end of the prompt.
- `max_active_sessions` caps how many vendor sessions run in parallel.
- Sessions are serialized per resolved workdir (git remote → `~/simple-orchestrator/git/<hash>`; null → per-task temp dir) to avoid conflicts.
- Cancellation is best-effort via `_vendor_kill(session_id)`.
- **Note**: The `memory-tool` skill is currently non-functional in distributed mode because `IOrchestratorClient` and the Web API lack the necessary memory management methods.

## Working with Workdirs

Use `resolve_workdir(workdir, cache_base)` from `workdir.py` to handle git cloning and cache path resolution. It requires an explicit `cache_base: Path`.

## Testing

Integration tests that require real vendor authentication must be marked/auto-skipped in CI.

## Quick validation

```bash
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
