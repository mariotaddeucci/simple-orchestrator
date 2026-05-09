# CLAUDE.md — `simple-orchestrator-database` (SQLite / repository)

Scope: `packages/simple-orchestrator-database/`.

## Why it exists

- Implement `IOrchestratorRepository` with SQLite (SQLModel/SQLAlchemy sync).
- Be the single backend for standalone mode and for `webapi` in distributed mode.

## Main goal

- Correct persistence: atomicity (claim/dequeue), status consistency, and retention/cleanup.

## Development guidelines

- No HTTP logic here (that belongs to `webapi` / `api-client`).
- Schema/query changes must follow updates in `core` (models/validators).
- Keep stable behavior for dependencies (`depends_on`) and old-item cleanup.
- Boolean column filters should be done in Python (post-fetch) to avoid SQLModel `Literal` type issues.

## Quick validation

This package is normally validated indirectly by `webapi` and `worker` tests:

```bash
uv run --package simple-orchestrator-webapi pytest packages/simple-orchestrator-webapi/
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
