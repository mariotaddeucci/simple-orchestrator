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

| Command | What it does |
|---|---|
| `simple-orchestrator webapi` | Starts the FastAPI REST server (`webapi_cli.main()`) |
| `simple-orchestrator worker` | Starts the queue runner against the running webapi (`worker_cli.main()`) |
| `simple-orchestrator tui` | Standalone TUI + embedded worker (direct DB, no HTTP) |
| `simple-orchestrator tui --distributed` | Distributed TUI, connects to a running webapi via HTTP |

Imports are lazy (`_import_or_exit(module, extra)`) so missing optional deps give a clear error at runtime.

## Standalone mode wiring

`simple-orchestrator tui` (default) creates one `OrchestratorDB` instance and injects it into both `StandaloneClient` (→ `OrchestratorTUI`) and `StandaloneSessionStore` (→ `WorkerRunner`). The `WorkerRunner` runs as a Textual `@work` background worker inside the TUI process — no subprocess, no webapi.

`simple-orchestrator tui --distributed` injects `OrchestratorApiClient(api_url, api_key)` into `OrchestratorTUI` only; a separate `worker` process must be running.

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
