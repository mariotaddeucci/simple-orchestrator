# CLAUDE.md — `simple-orchestrator-api-client` (HTTP client)

Scope: `packages/simple-orchestrator-api-client/`.

## Why it exists

- Allow `worker`/`tui` to consume the system via HTTP **without changing consumer code**.
- Implement the same repository contract, but by calling `webapi`.

## Main goal

- Parity: changes to endpoints/shapes must be reflected here and in `webapi` (via `core/api.py`).

## Development guidelines

- Map network errors/transients without inventing business rules.
- Respect settings (URL, API key, timeouts).

## Quick validation

```bash
uv run --package simple-orchestrator-api-client pytest packages/simple-orchestrator-api-client/
```
