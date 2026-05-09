# CLAUDE.md — `simple-orchestrator-webapi` (REST API)

Scope: `packages/simple-orchestrator-webapi/`.

## Why it exists

- Expose `IOrchestratorRepository` via REST (FastAPI) for distributed mode.
- Be a thin layer: validation and routing; persistence delegated to `database`.

## Main goal

- Keep parity with `simple-orchestrator-core/src/.../api.py` and `api-client`.

## Development guidelines

- Endpoints must use `core` models for request/response.
- Do not duplicate rules already enforced by the SQLite repository.
- `session_config_builder` fetches global MCPs from the DB (not from settings).

## Quick validation

```bash
uv run --package simple-orchestrator-webapi pytest packages/simple-orchestrator-webapi/
```
