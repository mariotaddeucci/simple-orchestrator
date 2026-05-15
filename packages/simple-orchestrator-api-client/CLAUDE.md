# CLAUDE.md — `simple-orchestrator-api-client` (HTTP client)

Scope: `packages/simple-orchestrator-api-client/`.

## Why it exists

- Allow `worker`/`tui` to consume the system over HTTP **without changing consumer code**.
- Implement the same `IOrchestratorClient` contract, backed by HTTP calls to `webapi`.

## Main goal

Parity: endpoint/shape changes in `webapi` must be reflected here and in `core/api.py`.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_api_client/client.py` | `OrchestratorApiClient` — async HTTP wrapper around all `webapi` endpoints |

`OrchestratorApiClient` is async. It is configured with `api_url`, `api_key`, and timeout settings from `WorkerSettings` or `TuiSettings`.

## Development rules

- Map network/transient errors without inventing business logic — propagate or raise as `RepositoryError`.
- Respect settings: `api_url`, `api_key`, request timeouts.
- Every new endpoint added to `webapi` needs a corresponding method here.
- Do not add caching or local state — the server is the source of truth.

## Quick validation

```bash
uv run --package simple-orchestrator-api-client pytest packages/simple-orchestrator-api-client/
```
