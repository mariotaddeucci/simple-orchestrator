# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands use `uv` — never activate the venv manually.

```bash
uv run python -c "..."          # run inline Python
uv run python <script>.py       # run Python scripts
uv add <package>                # add dependency
uv sync --frozen                # sync venv strictly from lock file (reproducible)
uv sync                         # update lockfile and sync (use when adding packages)
```

### Running the system

```bash
uv run simple-orchestrator worker    # start worker (queue runner + FastAPI on :8765)
uv run simple-orchestrator webapi    # start webapi only (no queue runner)
uv run simple-orchestrator-tui       # launch Textual terminal UI (REST client)
```

### Documentation lookup (Context7)

```bash
ctx7 get <library-name>         # fetch docs for a library (e.g. ctx7 get sqlmodel)
ctx7 search <query>             # search across libraries
```

Prefer `ctx7 get` over assumptions when working with third-party APIs (`sqlmodel`, `claude-agent-sdk`, `pydantic`, `ruff`, etc.).

### Code quality

```bash
uv run ruff check .             # lint (all rules: pyflakes, isort, security, bugbear…)
uv run ruff check --fix .       # lint + auto-fix
uv run ruff format .            # format code
uv run pyrefly check            # static type checking
```

### Tests

Each package has its own pytest config. Run per-package with `--package`:

```bash
# Run all tests for a package
uv run --package simple-orchestrator-core    pytest packages/simple-orchestrator-core/
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/
uv run --package simple-orchestrator-webapi  pytest packages/simple-orchestrator-webapi/

# Run a single test file
uv run --package simple-orchestrator-webapi  pytest packages/simple-orchestrator-webapi/tests/test_orchestrator_db.py

# Run a single test by name
uv run --package simple-orchestrator-core    pytest packages/simple-orchestrator-core/ -k test_parse_vendor_model

# Integration tests (require live vendor auth)
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/ -m integration
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/ -m "integration and copilot"
```

Integration tests require live vendor auth (copilot logged in, claude CLI authenticated, opencode running). They are auto-skipped in CI.

### Git hooks (prek)

```bash
uv run prek install             # install commit hooks (run once per clone)
uv run prek run --all-files     # run all hooks on every file manually
```

---

## Architecture

UV workspace with 7 packages. Multi-vendor async agent orchestrator supporting Claude Code (`claude_agent_sdk`), OpenCode (`opencode_ai`), and GitHub Copilot (`copilot`).

### Execution modes

The system supports two modes, governed by which implementation of `IOrchestratorRepository` is injected:

**Standalone** — TUI and worker connect directly to SQLite via `simple-orchestrator-database`. No REST API needed.

**Distributed** — TUI and worker talk to a `simple-orchestrator-webapi` instance over HTTP. The HTTP client (`simple-orchestrator-api-client`) implements the same interfaces, so consumer code is unchanged.

```
Standalone:
  TUI / Worker → OrchestratorDB (simple-orchestrator-database) → SQLite

Distributed:
  TUI / Worker → ApiClient (simple-orchestrator-api-client) → WebAPI → OrchestratorDB → SQLite
```

### Workspace packages

| Package | Module | Role |
|---|---|---|
| `simple-orchestrator` | `simple_orchestrator` | CLI dispatch: `worker`, `webapi` subcommands |
| `simple-orchestrator-core` | `simple_orchestrator_core` | Pydantic models, Protocols (interfaces), settings, validators |
| `simple-orchestrator-database` | `simple_orchestrator_database` | SQLite persistence; implements `IOrchestratorRepository` |
| `simple-orchestrator-webapi` | `simple_orchestrator_webapi` | FastAPI REST server; delegates all DB access to `simple-orchestrator-database` |
| `simple-orchestrator-worker` | `simple_orchestrator_worker` | Queue runner + vendor implementations |
| `simple-orchestrator-api-client` | `simple_orchestrator_api_client` | HTTP client; implements `IOrchestratorRepository` via REST |
| `simple-orchestrator-tui` | `simple_orchestrator_tui` | Textual terminal UI; consumes `IOrchestratorRepository` |

All source lives under `packages/<package-name>/src/<module_name>/`.

---

## Core package — the contract layer

`simple-orchestrator-core` is the only package imported by all others. It defines:

### Repository interfaces (`interfaces.py`)

Five `typing.Protocol` classes, combined into one:

```
IOrchestratorRepository
  ├── IAgentRepository     — agents CRUD (list/get/upsert/delete)
  ├── IQueueRepository     — queue ops (enqueue/dequeue/update/cancel/cleanup)
  ├── ISessionRepository   — session lifecycle (save/update_status/get/list)
  ├── IMemoryRepository    — per-agent memory (save/get/delete/list)
  └── IWorkerRepository    — heartbeat ops (upsert/list_alive)
```

Any code that reads or writes data must type-annotate against these Protocols, never against a concrete class. This is what enables swapping SQLite for HTTP at injection time.

### Pydantic models (`models/`)

All Pydantic v2 (or SQLModel where persistence is needed). Key models:

| Model | Purpose |
|---|---|
| `SessionConfig` | Full session input: prompt, model, workdir, mcp_servers, skills, agents, subagents, env, max_turns, permission_mode |
| `SessionRecord` | Persisted session row: id (ULID), vendor, prompt, workdir, started_at, status, ended_at, vendor_session_id |
| `QueueItem` | Queue row: id, agent_id, prompt, workdir, status, session_id, depends_on, note |
| `AgentRecord` | Persisted agent definition: id, name, vendor, model, workdir, prompt, mcp_servers, skills |
| `McpConfig` | Discriminated union on `type`: `McpStdioConfig | McpSseConfig | McpHttpConfig` |
| `WorkerHeartbeat` | Heartbeat payload (ULID id, type, name) |
| `ModelInfo` | Returned by `list_models()`: id, name, vendor |

`SessionConfig.agents` = foreground agents. `SessionConfig.subagents` = background agents. Claude Code merges both into `ClaudeAgentOptions.agents`.

### API request/response models (`api.py`)

`EnqueueRequest`, `EnqueueResponse`, `QueueUpdateRequest`, `QueueDequeueResponse`, `AgentUpsertRequest`, `SessionUpdateRequest`, etc. These are the Pydantic shapes for both the REST endpoints and the HTTP client. Defining them in `core` means both sides share the exact same validation.

### Validators (`validators.py`)

`ValidULID`, `ValidAgentId`, `ValidAlias`, `ValidDepRef`, `ValidWorkdir` — all `Annotated` types with `AfterValidator`. Applied to model fields at declaration; validation runs automatically on construction. `ValidWorkdir` blocks null bytes and path traversal.

### Settings (`settings.py`)

`WebApiSettings`, `WorkerSettings`, `TuiSettings` — all `pydantic_settings.BaseSettings`. Load from `orchestrator.toml`, then `pyproject.toml [tool.simple-orchestrator]`, then env vars (`ORCHESTRATOR_*` prefix). `AgentSettings` lives inside `[agents.<id>]`; prompt is either inline or `prompt_file = "path"`.

---

## Database package (`simple-orchestrator-database`)

Single class `OrchestratorDB` in `repository.py`. Implements `IOrchestratorRepository` structurally (no explicit `class OrchestratorDB(IOrchestratorRepository)` — structural Protocol conformance is checked by the type checker).

- Uses SQLModel (SQLAlchemy sync) + SQLite. `build_engine()` in `engine.py` runs `SQLModel.metadata.create_all` on startup.
- All models imported at engine build time to register SQLAlchemy metadata (`agent_record`, `queue_item`, `session`, `memory_record`, `worker_heartbeat_record`).
- Context manager (`__enter__`/`__exit__`) and explicit `connect()`/`close()` both supported.
- `_resolve_workdir()` — `None` → `tempfile.mkdtemp()`; existing dir → tries `git rev-parse --show-toplevel`; else as-is.
- `dequeue_next()` uses optimistic locking: fetches pending rows, then `UPDATE … WHERE status='pending'` to claim one atomically. Handles `depends_on` chains: auto-fails blocked items when a dependency fails/is cancelled/is missing.

**Retention:** `cleanup_old_completed_items(max_items, max_age_days)` — keeps at most `max_items` most recent completed queue items and drops anything older than `max_age_days`. Called by the worker after each task completes.

The webapi's `db/` subdirectory is now a thin re-export shim (`from simple_orchestrator_database import OrchestratorDB`). Real implementation lives in the database package.

---

## Worker package (`simple-orchestrator-worker`)

### Vendor polymorphism (`vendors/base.py`)

`BaseVendor` ABC. All vendors override:
- `vendor_name: str` — property
- `_run_session(session_id, config)` — background task body
- `_vendor_kill(session_id)` — native abort/disconnect
- `execute_session(config)` — `AsyncIterator` for direct streaming (no DB)
- `list_models()` — available `ModelInfo` list

Concrete methods on `BaseVendor` (not overridden):
- `run(config) -> str` — generates ULID, saves `SessionRecord(status="running")`, spawns `asyncio.Task`, returns immediately
- `kill(session_id)` — cancels task, calls `_vendor_kill`, sets `status="killed"`
- `wait(session_id)` — blocks until session completes, returns `SessionRecord`

### Queue runner (`worker_runner.py`)

`QueueRunner` polls the DB and dispatches items with bounded parallelism:
- At most `settings.max_active_sessions` concurrent items (asyncio semaphore)
- Items sharing `workdir` are serialised (per-dir `asyncio.Lock`)
- `depends_on` delays items until referenced IDs reach `completed`
- `start()` / `stop()` for background loop; `run_until_empty()` for one-shot drain

Agent definitions come from `settings.agents` (`orchestrator.toml`) — versionable, checked into git. Global `mcp_servers` and `skills` merge with per-agent ones in `_build_session_config()`.

### Worker heartbeats

Worker sends ULID-keyed periodic heartbeats to WebAPI (`POST /heartbeat`). WebAPI upserts into `worker_heartbeats` table and uses TTL (`heartbeat_ttl_seconds`) to determine liveness on `GET /health`.

### Logging (`logging_config.py`)

Two log streams — import the right one per module:
- `get_internal_logger(__name__)` — `logs/orchestrator.log` (queue, DB, polling)
- `get_vendor_logger(__name__)` — `logs/vendor.log` (agent execution)

`DEBUG` mode adds `[filename.py:line]` to every log line.

---

## Vendor-specific notes

**ClaudeCodeVendor** — passes `session_id` to `ClaudeAgentOptions` so the SDK uses our ULID. MCP servers mapped `McpConfig → McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig` TypedDicts. Skills flattened to `list[str]`.

**OpenCodeVendor** — HTTP client (`AsyncOpencode`). Creates session via `session.create()`, stores returned `vendor_session_id`. Kill calls `session.abort(vendor_session_id)`.

**GithubCopilotVendor** — spawns CLI subprocess via `CopilotClient`. Session handle in `_active_handles`. Kill calls `session.abort()` then `session.disconnect()`.
