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
| `src/simple_orchestrator/cli.py` | `main()` — Typer-based subcommand dispatch |

## CLI subcommands

| Command | What it does |
|---|---|
| `simple-orchestrator webapi` (or `start`) | Starts the FastAPI REST server (`webapi_cli.main()`) |
| `simple-orchestrator worker` | Starts the queue runner (`worker_cli.main()`) |
| `simple-orchestrator-tui` | Starts the Textual TUI (`tui.main()`) — separate entrypoint |

Imports are lazy (`_import_or_exit(module, extra)`) so missing optional deps produce a clear error instead of a hard crash at startup.

The CLI is built with **Typer**. Keep subcommand handlers minimal; business logic belongs in the specialized packages.

## Standalone mode wiring

In standalone mode (direct SQLite, no HTTP), `StandaloneClient` and `StandaloneSessionStore` are injected into `worker`/`tui` to share a single `OrchestratorDB` instance without any network calls. This is the default when `webapi` is not explicitly started separately.

## Development rules

- Keep subcommand handlers minimal: parse args, load settings, call the package's entry function.
- Business logic belongs in the specialized packages, not here.
- CLI changes usually require documentation updates and end-to-end validation with the run commands.

## Quick validation

```bash
uv run ruff check packages/simple-orchestrator/
uv run ruff format packages/simple-orchestrator/
```
