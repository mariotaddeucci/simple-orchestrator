# CLAUDE.md — `simple-orchestrator` (CLI / wiring)

Scope: `packages/simple-orchestrator/`.

## Why it exists

- Provide CLI entrypoints to start `worker`, `webapi`, and `tui`.
- Centralize wiring (settings + DI) without coupling consumers to concrete implementations.

## Main goal

Ensure CLI invocations correctly configure settings, the repository (SQLite direct or HTTP), and logging.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator/cli.py` | `main()` — Typer app; `cmd_webapi`, `cmd_worker`, `cmd_tui` subcommands |
| `src/simple_orchestrator/standalone.py` | `StandaloneClient` (satisfies `IOrchestratorClient`) + `StandaloneSessionStore` |

## CLI subcommands

| Command | Mode | What it does |
|---|---|---|
| `simple-orchestrator standalone` | Standalone | TUI + embedded worker sharing one `OrchestratorDB` directly (no HTTP) |
| `simple-orchestrator webapi` | Distributed | FastAPI REST server — owns the SQLite DB |
| `simple-orchestrator worker` | Distributed | Worker process — connects to running webapi via HTTP |
| `simple-orchestrator tui` | Distributed | TUI only — connects to running webapi via HTTP |
| `simple-orchestrator frontend` | Distributed | Web Dashboard only — connects to running webapi via HTTP |

Calling individual services (`webapi`, `worker`, `tui`, `frontend`) is the **distributed** mode — each process is separate and communicates via HTTP. Call `standalone` when you want everything in one process.

Imports are lazy (`_import_or_exit(module, extra)`) so missing optional deps give a clear error at runtime.

## Standalone mode wiring

`standalone` creates one `OrchestratorDB` instance and injects it into both `StandaloneClient` (→ `OrchestratorTUI`) and `StandaloneSessionStore` (→ `WorkerRunner`). The `WorkerRunner` runs as a Textual `@work` background worker inside the TUI process — no subprocess, no webapi needed.

`tui` (distributed) injects `OrchestratorApiClient(api_url, api_key)` into `OrchestratorTUI`; a separate `webapi` and `worker` must be running.

Both clients satisfy `IOrchestratorClient` — consumers are never typed against a concrete class.

## Development rules

- Keep subcommand handlers minimal: parse args, load settings, call the package's entry function.
- Business logic belongs in the specialized packages, not here.
- CLI changes usually require documentation updates and end-to-end validation with the run commands.

## Quick validation

```bash
uv run ruff check packages/simple-orchestrator/
uv run ruff format packages/simple-orchestrator/
```
