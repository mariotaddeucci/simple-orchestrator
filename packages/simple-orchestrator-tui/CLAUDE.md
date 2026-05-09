# CLAUDE.md — `simple-orchestrator-tui` (Textual UI)

Scope: `packages/simple-orchestrator-tui/`.

## Why it exists

- Terminal interface to enqueue and monitor sessions.
- Consume the repository (SQLite direct or HTTP via `api-client`) without coupling to implementations.

## Main goal

Predictable, stable UX; keep the TUI as a pure client (no persistence logic here).

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_tui/app.py` | `OrchestratorTUI` (main Textual app) + `EnqueueModal` |

## UI components

**`OrchestratorTUI`** — main app:
- `DataTable` showing the queue (live refresh).
- Key bindings: `q` quit, `r` refresh, `a` enqueue.
- Uses `OrchestratorApiClient` (HTTP) to fetch and update queue items.

**`EnqueueModal`** — modal dialog:
- Inputs: `agent_id`, `prompt`, `workdir`.
- Submits via `api-client` `enqueue()`.

## Development rules

- No direct dependency on `database`/SQL — always go through the injected repository.
- Flow changes must be validated by running the TUI against the chosen mode (direct DB or HTTP).
- UI state (selected row, filters) is ephemeral — never persist it.

## Quick validation

This package is validated manually by running the TUI. When unit tests exist, run them per-package:

```bash
uv run --package simple-orchestrator-tui pytest packages/simple-orchestrator-tui/
```
