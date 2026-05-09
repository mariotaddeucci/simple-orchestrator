# CLAUDE.md — `simple-orchestrator` (CLI / wiring)

Scope: `packages/simple-orchestrator/`.

## Why it exists

- Provide CLI entrypoints to start `worker`, `webapi`, and `tui`.
- Centralize wiring (settings + DI) without coupling consumers to concrete implementations.

## Main goal

- Ensure running via CLI correctly configures: settings, repository (direct SQLite or HTTP), and logging.

## Development guidelines

- Keep subcommands simple (parse/dispatch) and push business rules to specialized packages.
- Changes here generally require CLI documentation updates and end-to-end validation.

## Quick validation

```bash
uv run ruff check packages/simple-orchestrator/
uv run ruff format packages/simple-orchestrator/
```
