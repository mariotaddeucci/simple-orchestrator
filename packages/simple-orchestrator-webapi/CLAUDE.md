# CLAUDE.md — `simple-orchestrator-webapi` (REST API)

Scope: `packages/simple-orchestrator-webapi/`.

## Why it exists

- Expose `IOrchestratorRepository` over REST (FastAPI) for distributed mode.
- Thin layer: validation and routing only; persistence delegated to `database`.

## Main goal

Maintain parity with `simple-orchestrator-core/src/.../api.py` and `api-client`.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_webapi/api.py` | All FastAPI routes |
| `src/simple_orchestrator_webapi/webapi_cli.py` | CLI entry point (`uvicorn` startup) |
| `src/simple_orchestrator_webapi/logging_config.py` | `get_internal_logger`, `get_vendor_logger`, `setup_logging` |
| `src/simple_orchestrator_webapi/session_config_builder.py` | `build_session_config(agent, queue_item)` → `SessionConfig`; fetches global MCPs from DB |
| `src/simple_orchestrator_webapi/db/orchestrator.py` | DB dependency injection helper |

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | List alive workers (TTL-based liveness check) |
| `POST` | `/heartbeat` | Upsert worker heartbeat |
| `GET` | `/agents` | List all agents |
| `GET` | `/agents/{agent_id}` | Get single agent |
| `POST` | `/agents` | Upsert agent |
| `DELETE` | `/agents/{agent_id}` | Delete agent |
| `POST` | `/queue` | Enqueue task |
| `GET` | `/queue` | List queue (filter: `status`, `agent_id`) |
| `GET` | `/queue/{item_id}` | Get queue item |
| `PATCH` | `/queue/{item_id}` | Update queue item status |
| `POST` | `/queue/{item_id}/cancel` | Cancel (pending → cancelled) |
| `POST` | `/queue/dequeue` | Dequeue next item → 204 if empty |
| `GET` | `/sessions` | List sessions (filter: `vendor`, `status`) |
| `GET` | `/sessions/{session_id}` | Get session |
| `POST` | `/sessions` | Save session |
| `PATCH` | `/sessions/{session_id}` | Update session status |

## Auth

`X-API-Key` header required on all endpoints. If `api_key` is not set in `WebApiSettings`, auth is skipped (dev mode). Always change the default `"change-me"` key in production.

## Development rules

- Endpoints must use `core` request/response models — no local schema definitions.
- Do not duplicate business rules that already exist in the repository (e.g., `depends_on` resolution).
- `session_config_builder.py` merges `AgentRecord` + `QueueItem` into a `SessionConfig` — update it when new agent fields are added.

## Quick validation

```bash
uv run --package simple-orchestrator-webapi pytest packages/simple-orchestrator-webapi/
```
