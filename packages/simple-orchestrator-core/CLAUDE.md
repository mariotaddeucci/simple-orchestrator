# CLAUDE.md — `simple-orchestrator-core` (contract)

Scope: `packages/simple-orchestrator-core/`.

## Why it exists

- Be the **shared layer** consumed by all other packages.
- Define stable contracts: Pydantic models, settings, validators, and Protocols (`IOrchestratorRepository`).

## Main goal

Evolve schemas carefully — changes here ripple into `database`, `webapi`, `api-client`, `worker`, and `tui`.

## Development rules

- Prefer backward compatibility (e.g., coercions/validators for legacy schemas).
- API shapes live here so `webapi` and `api-client` validate identically.
- Protocols must be the type used by consumers — do not depend on concrete implementations.
- All primary keys are ULIDs; never use UUIDs or auto-increment integers.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_core/interfaces.py` | Repository Protocols (see below) |
| `src/simple_orchestrator_core/models/` | Domain models (SQLModel + plain Pydantic) |
| `src/simple_orchestrator_core/api.py` | REST request/response shapes + `auth_headers()` |
| `src/simple_orchestrator_core/settings.py` | `WebApiSettings`, `WorkerSettings`, `TuiSettings` |
| `src/simple_orchestrator_core/validators.py` | Shared validation helpers |
| `src/simple_orchestrator_core/vendor_selector.py` | Parses `"vendor/model"` strings |
| `src/simple_orchestrator_core/mcp_inputs.py` | MCP server configuration helpers |

## Repository Protocols (`interfaces.py`)

`IOrchestratorRepository` composes five sub-protocols:

**`IAgentRepository`**
- `list_agents()` → `list[AgentRecord]`
- `get_agent(agent_id)` → `AgentRecord | None`
- `upsert_agent(req: AgentUpsertRequest)` → `AgentRecord`
- `delete_agent(agent_id)` → `bool`

**`IQueueRepository`**
- `enqueue(agent_id, prompt, workdir, depends_on, item_id)` → `QueueItem`
- `list_queue(*, status, agent_id)` → `list[QueueItem]`
- `get_queue_item(item_id)` → `QueueItem | None`
- `update_queue_item(item_id, *, status, session_id, ended_at, started_at, note)` → `None`
- `update_queue_item_api(item_id, req: QueueUpdateRequest)` → `QueueItem | None`
- `cancel_queue_item(item_id)` → `None`
- `reset_to_pending(item_id)` → `None`
- `add_task_note(item_id, note)` → `bool`
- `has_duplicate_pending(agent_id, prompt)` → `bool`
- `dequeue_next()` → `QueueItem | None`
- `cleanup_old_completed_items(*, max_items=15, max_age_days=7)` → `int`

**`ISessionRepository`**
- `save_session(record: SessionRecord)` / `save(record)` → `None`
- `update_session_status(session_id, req: SessionUpdateRequest)` → `None`
- `update_status(session_id, status, ended_at, vendor_session_id)` → `None`
- `get_session(session_id)` / `get(session_id)` → `SessionRecord | None`
- `list_sessions(*, vendor, status)` → `list[SessionRecord]`

**`IMemoryRepository`**
- `save_memory(agent_id, description, content)` → `MemoryRecord`
- `get_memory(memory_id)` → `MemoryRecord | None`
- `delete_memory(memory_id)` → `bool`
- `list_memories(agent_id)` → `list[MemoryRecord]`

**`IWorkerRepository`**
- `upsert_worker_heartbeat(heartbeat: WorkerHeartbeat)` → `WorkerHeartbeatRecord`
- `list_alive_workers(*, ttl_seconds)` → `list[WorkerHeartbeatRecord]`

Plus `connect()` / `close()` on the composite `IOrchestratorRepository`.

## Domain models

| Model | SQLModel | Key fields |
|---|---|---|
| `AgentRecord` | ✅ | `id` (ULID pk), `name`, `nickname`, `vendor`, `model`, `workdir`, `task_timeout_minutes`, `mcp_servers`, `skills`, `skill_globs` |
| `QueueItem` | ✅ | `id`, `agent_id`, `prompt`, `workdir`, `status`, `session_id`, `depends_on`, `note`, timestamps |
| `SessionRecord` | ✅ | `id`, `vendor`, `prompt`, `workdir`, `status`, `vendor_session_id`, timestamps |
| `MemoryRecord` | ✅ | `id`, `agent_id`, `description`, `content`, `updated_at` |
| `WorkerHeartbeatRecord` | ✅ | `id`, `type`, `name`, `last_heartbeat_at` |
| `AgentConfig` | ❌ | `description`, `prompt`, `model`, `tools`, `skills`, `mcp_servers`, `max_turns`, `effort`, `permission_mode` |
| `SessionConfig` | ❌ | `prompt`, `model`, `workdir`, `mcp_servers`, `skills`, `max_turns`, `permission_mode`, `env` |
| `McpConfig` | ❌ | Union of `McpStdioConfig | McpSseConfig | McpHttpConfig` (discriminator: `type`) |

## Settings defaults

| Setting | Class | Default |
|---|---|---|
| `db_path` | `WebApiSettings` | `"orchestrator.db"` |
| `webapi_host` / `webapi_port` | `WebApiSettings` | `127.0.0.1:8765` |
| `api_key` | `WebApiSettings` | `"change-me"` |
| `heartbeat_ttl_seconds` | `WebApiSettings` | `30.0` |
| `max_completed_items` | `WebApiSettings` | `15` |
| `max_completed_age_days` | `WebApiSettings` | `7` |
| `max_active_sessions` | `WorkerSettings` | `4` |
| `poll_interval_seconds` | `WorkerSettings` | `1.0` |
| `heartbeat_interval_seconds` | `WorkerSettings` | `10.0` |
| `worker_id` | `WorkerSettings` | auto ULID at startup |

## Quick validation

```bash
uv run --package simple-orchestrator-core pytest packages/simple-orchestrator-core/
```
