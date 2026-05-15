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
- `Literal` types must NOT be used as SQLModel table field types — use `str` and validate at the API layer.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_core/interfaces.py` | Repository Protocols (see below) |
| `src/simple_orchestrator_core/models/` | Domain models (SQLModel + plain Pydantic) |
| `src/simple_orchestrator_core/api.py` | REST request/response shapes + `auth_headers()` |
| `src/simple_orchestrator_core/settings.py` | `WebApiSettings`, `WorkerSettings`, `TuiSettings`, `FrontendSettings` |
| `src/simple_orchestrator_core/validators.py` | Shared validation helpers |
| `src/simple_orchestrator_core/vendor_selector.py` | Parses `"vendor/model"` strings |
| `src/simple_orchestrator_core/mcp_inputs.py` | MCP server configuration helpers |
| `src/simple_orchestrator_core/schedule.py` | `compute_next_run()` for interval/cron scheduling |

## Protocols (`interfaces.py`)

### `IOrchestratorRepository` (sync — database only)

Composes seven sub-protocols implemented by `OrchestratorDB`:

**`IAgentRepository`** — `list_agents`, `get_agent`, `upsert_agent`, `delete_agent`

**`IQueueRepository`** — `enqueue`, `list_queue`, `get_queue_item`, `update_queue_item`, `update_queue_item_api`, `cancel_queue_item`, `reset_to_pending`, `add_task_note`, `has_duplicate_pending`, `dequeue_next`, `cleanup_old_completed_items`

**`ISessionRepository`** — `save_session`/`save`, `update_session_status`, `update_status`, `get_session`/`get`, `list_sessions`

**`IMemoryRepository`** — `save_memory`, `get_memory`, `delete_memory`, `list_memories`

**`IWorkerRepository`** — `upsert_worker_heartbeat`, `list_alive_workers`

**`IMcpRepository`** — `list_mcps`, `get_mcp`, `upsert_mcp`, `delete_mcp`

**`IEventRepository`** — `list_events`, `get_event`, `create_event`, `update_event`, `delete_event`, `get_due_events`, `update_next_run`

Plus `connect()` / `close()` on the composite `IOrchestratorRepository`.

### `IOrchestratorClient` (async — used by worker, TUI, and standalone wiring)

Single async contract satisfied by **both** `OrchestratorApiClient` (HTTP → webapi) and `StandaloneClient` (direct SQLite). Consumers (`WorkerRunner`, `ApiSessionStore`, `OrchestratorTUI`) are typed against this Protocol — never against a concrete class.

```python
class IOrchestratorClient(Protocol):
    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> None
    async def list_agents(self) -> list[AgentRecord]
    async def get_agent(self, agent_id: str) -> AgentRecord
    async def upsert_agent(self, req: AgentUpsertRequest) -> AgentRecord
    async def delete_agent(self, agent_id: str) -> None
    async def enqueue(self, req: EnqueueRequest) -> QueueItem
    async def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[QueueItem]
    async def get_queue_item(self, item_id: str) -> QueueItem
    async def update_queue_item(self, item_id: str, req: QueueUpdateRequest) -> QueueItem
    async def cancel(self, item_id: str) -> None
    async def dequeue_next(self) -> QueueDequeueResponse | None
    async def create_session(self, req: SessionCreateRequest) -> None
    async def update_session(self, session_id: str, req: SessionUpdateRequest) -> None
    async def list_sessions(self, *, vendor: str | None = None, status: str | None = None) -> list[SessionRecord]
    async def get_session(self, session_id: str) -> SessionRecord
    async def list_mcps(self, *, is_global: bool | None = None, enabled: bool | None = None) -> list[McpRecord]
    async def get_mcp(self, mcp_id: str) -> McpRecord
    async def upsert_mcp(self, req: McpCreateRequest) -> McpRecord
    async def delete_mcp(self, mcp_id: str) -> None
    async def list_events(self, *, enabled: bool | None = None) -> list[EventRecord]
    async def get_event(self, event_id: str) -> EventRecord
    async def create_event(self, req: EventCreateRequest) -> EventRecord
    async def update_event(self, event_id: str, req: EventUpdateRequest) -> EventRecord
    async def delete_event(self, event_id: str) -> None
    async def trigger_event(self, event_id: str) -> QueueItem
```

**Rule**: never add `OrchestratorApiClient` or `StandaloneClient` as a type annotation outside their own packages. Always use `IOrchestratorClient`.

## Domain models

| Model | SQLModel | Key fields |
|---|---|---|
| `AgentRecord` | ✅ | `id` (ULID pk), `name`, `nickname`, `prompt`, `vendor`, `model`, `task_timeout_minutes`, `mcp_servers`, `skills`, `skill_globs`, `created_at` |
| `QueueItem` | ✅ | `id`, `agent_id`, `prompt`, `workdir`, `status`, `session_id`, `depends_on`, `note`, `created_at`, `started_at`, `ended_at` |
| `SessionRecord` | ✅ | `id`, `vendor`, `prompt`, `workdir`, `started_at`, `status`, `ended_at`, `vendor_session_id` |
| `MemoryRecord` | ✅ | `id`, `agent_id`, `description`, `content`, `updated_at` |
| `WorkerHeartbeatRecord` | ✅ | `id`, `type`, `name`, `last_heartbeat_at` |
| `McpRecord` | ✅ | `id`, `name`, `type` (str: stdio/sse/http), `command`, `args`, `env`, `url`, `headers`, `is_global`, `enabled` |
| `EventRecord` | ✅ | `id`, `name`, `agent_id`, `prompt`, `workdir`, `schedule_type` (str: interval/cron), `interval_minutes`, `cron_expression`, `next_run`, `enabled` |
| `AgentConfig` | ❌ | `description`, `prompt`, `model`, `tools`, `skills`, `mcp_servers`, `max_turns`, `effort`, `permission_mode` |
| `SessionConfig` | ❌ | `prompt`, `model`, `workdir`, `mcp_servers`, `skills`, `agents`, `subagents`, `max_turns`, `permission_mode`, `env` |
| `McpConfig` | ❌ | Union of `McpStdioConfig | McpSseConfig | McpHttpConfig` (discriminator: `type`) |

## Settings defaults

| Setting | Class | Default |
|---|---|---|
| `db_path` | `WebApiSettings`, `WorkerSettings`, `TuiSettings` | `~/simple-orchestrator/orchestrator.db` |
| `logs_dir` | `WebApiSettings`, `WorkerSettings`, `TuiSettings` | `~/simple-orchestrator/logs` |
| `git_cache_dir` | `WorkerSettings` | `~/simple-orchestrator/git` |
| `webapi_host` / `webapi_port` | `WebApiSettings` | `127.0.0.1:8765` |
| `api_key` | `WebApiSettings` | `"change-me"` |
| `heartbeat_ttl_seconds` | `WebApiSettings` | `30.0` |
| `max_completed_items` | `WebApiSettings` | `15` |
| `max_completed_age_days` | `WebApiSettings` | `7` |
| `max_active_sessions` | `WorkerSettings` | `4` |
| `poll_interval_seconds` | `WorkerSettings` | `1.0` |
| `heartbeat_interval_seconds` | `WorkerSettings` | `10.0` |
| `worker_id` | `WorkerSettings` | auto ULID at startup |
| `standalone` | `TuiSettings` | `True` |
| `frontend_host` / `frontend_port` | `FrontendSettings` | `127.0.0.1:8766` |

## Quick validation

```bash
uv run --package simple-orchestrator-core pytest packages/simple-orchestrator-core/
```
