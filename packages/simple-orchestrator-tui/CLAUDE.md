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

**`OrchestratorTUI(client: IOrchestratorClient, *, background_worker=None)`** — main app:
- Three tabs: **Queue**, **Agents**, **Events** (live refresh every 2 s).
- Key bindings: `q` quit, `r` refresh, `a` enqueue.
- `background_worker`: optional async callable run as a Textual `@work` worker on mount (used by standalone mode to embed `WorkerRunner`).
- All data access goes through `client` — never imports DB or HTTP code directly.

**`EnqueueModal`** — modal dialog:
- Shows an agent dropdown (populated from `client.list_agents()`).
- Inputs: `agent_id` (or select), `prompt`, `workdir`.
- Submits via `client.enqueue(EnqueueRequest(...))`.

## Development rules

- No direct dependency on `database`/SQL — always go through the injected repository.
- Flow changes must be validated by running the TUI against the chosen mode (direct DB or HTTP).
- UI state (selected row, filters) is ephemeral — never persist it.

## Quick validation

This package is validated manually by running the TUI. When unit tests exist, run them per-package:

```bash
uv run --package simple-orchestrator-tui pytest packages/simple-orchestrator-tui/
```
