# CLAUDE.md — `simple-orchestrator-database` (SQLite / repository)

Scope: `packages/simple-orchestrator-database/`.

## Why it exists

- Implement `IOrchestratorRepository` using SQLite (SQLModel / SQLAlchemy sync).
- Serve as the sole persistence backend for standalone mode and for `webapi` in distributed mode.

## Main goal

Correct persistence: atomicity (claim/dequeue), consistent status transitions, and retention/cleanup.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_database/engine.py` | `build_engine(db_path)` — creates SQLite engine and all tables |
| `src/simple_orchestrator_database/repository.py` | `OrchestratorDB` — full implementation of `IOrchestratorRepository` |

## Database schema (auto-created by SQLModel)

| Table | Primary key | Notable columns |
|---|---|---|
| `agents` | `id` (ULID) | `name`, `nickname`, `prompt`, `vendor`, `model`, `task_timeout_minutes`, `mcp_servers` (JSON), `skills` (JSON), `skill_globs` (JSON), `created_at` |
| `queue` | `id` (ULID) | `agent_id`, `workdir` (git remote or null), `status`, `session_id`, `depends_on` (JSON), `note`, `created_at`, `started_at`, `ended_at` |
| `sessions` | `id` (ULID) | `vendor`, `prompt`, `workdir`, `started_at`, `status`, `ended_at`, `vendor_session_id` |
| `memory` | `id` (ULID) | `agent_id`, `description`, `content`, `updated_at` |
| `worker_heartbeats` | `id` (ULID) | `type`, `name`, `last_heartbeat_at` |
| `mcps` | `id` (ULID) | Global MCP server definitions available to all agents |
| `events` | `id` (ULID) | Scheduled events with `next_run`, `interval`/`cron`, `agent_id` |

## Key behaviors

- **`dequeue_next()`** — atomically claims the next `pending` item; checks `depends_on` items are all complete before yielding.
- **`enqueue()`** — stores `workdir` exactly as provided (git remote URL or null). Worker resolves to a temp dir (null) or a cached clone (git remote) at execution time.
- **`cleanup_old_completed_items()`** — keeps at most `max_items` (default 15) recent completed items, removing those older than `max_age_days` (default 7).
- **`upsert_worker_heartbeat()`** — inserts or updates `last_heartbeat_at` for the given worker ULID.
- **`list_alive_workers(ttl_seconds)`** — returns heartbeat records where `last_heartbeat_at >= now - ttl`.

## Development rules

- No HTTP logic here — that belongs to `webapi` / `api-client`.
- Schema/query changes must align with `core` model updates.
- Keep `depends_on` checking and `dequeue_next()` atomic to avoid double-dispatch under concurrent workers.
- Boolean column filters should be done in Python (post-fetch) to avoid SQLModel `Literal` type issues.
- `SessionRecord.workdir` is non-nullable; ensure a valid path string is provided when creating records.

## Quick validation

This package is validated indirectly through `webapi` and `worker` tests:

```bash
uv run --package simple-orchestrator-webapi pytest packages/simple-orchestrator-webapi/
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
