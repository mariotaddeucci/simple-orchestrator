# Contributing

## Development setup

```bash
git clone https://github.com/mariotaddeucci/simple-orchestrator
cd simple-orchestrator
uv sync --frozen          # install dependencies
uv run prek install       # install git hooks (lint + format + type check on commit)
```

---

## Architecture

The project is a **UV workspace** with 7 packages. The central principle is separation of contracts (interfaces) from implementation: `simple-orchestrator-core` defines what each component must do; the other packages implement or consume those definitions.

### Packages and responsibilities

| Package | Module | Focus |
|---|---|---|
| `simple-orchestrator` | `simple_orchestrator` | CLI entrypoints: `standalone`, `webapi`, `worker`, `tui` |
| `simple-orchestrator-core` | `simple_orchestrator_core` | **Contracts**: Pydantic models, Protocol interfaces, settings, validators |
| `simple-orchestrator-database` | `simple_orchestrator_database` | **Persistence**: implements `IOrchestratorRepository` via SQLite/SQLModel |
| `simple-orchestrator-webapi` | `simple_orchestrator_webapi` | **REST API**: FastAPI; delegates all data access to the `database` package |
| `simple-orchestrator-worker` | `simple_orchestrator_worker` | **Execution**: task queue, event scheduling, vendors (Claude/OpenCode/Copilot/Jules) |
| `simple-orchestrator-api-client` | `simple_orchestrator_api_client` | **HTTP client**: consumes the REST API; implements `IOrchestratorClient` |
| `simple-orchestrator-tui` | `simple_orchestrator_tui` | **Interface**: Textual TUI; consumes the REST API via api-client |

---

## Architecture diagrams

### Standalone mode

In standalone mode (`simple-orchestrator standalone`), TUI and worker share one `OrchestratorDB` instance directly — no HTTP, no subprocesses. The worker runs as a Textual background task inside the TUI process.

```
  simple-orchestrator standalone (single process)
  ┌────────────────────────────────────────────────────────────┐
  │                                                            │
  │  OrchestratorTUI (Textual)                                 │
  │  ┌──────────────┐                                         │
  │  │  Queue tab   │                                         │
  │  │  Agents tab  │◄──────────────────────┐                 │
  │  │  Events tab  │                       │                 │
  │  └──────────────┘                       │ StandaloneClient│
  │                                         │                 │
  │  WorkerRunner (@work background task)   │ OrchestratorDB  │
  │  ┌──────────────┐       ┌───────────────▼──────────────┐  │
  │  │  QueueRunner │◄─────►│  SQLite (direct, no HTTP)    │  │
  │  │  EventSched  │       └──────────────────────────────┘  │
  │  └──────────────┘                                         │
  └────────────────────────────────────────────────────────────┘
```

To use distributed mode instead, run each service separately:

```bash
uv run simple-orchestrator webapi   # owns the DB
uv run simple-orchestrator worker   # connects via HTTP
uv run simple-orchestrator tui      # connects via HTTP
```

### Distributed mode

TUI and worker communicate with WebAPI via HTTP. Each component runs as an independent process.

```
  simple-orchestrator-tui          simple-orchestrator-worker
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  Textual TUI         │         │  QueueRunner             │
  │  (Queue/Agents/      │         │  (processes tasks,       │
  │   Events tabs)       │         │   schedules events)      │
  └──────────┬───────────┘         └────────────┬─────────────┘
             │                                  │
             │  HTTP / REST                     │  HTTP / REST
             │                                  │
             └──────────────┬───────────────────┘
                            │
             simple-orchestrator-webapi
             ┌─────────────────────────────────┐
             │  FastAPI                        │
             │  /queue /agents /sessions       │
             │  /mcps /events /health          │
             └──────────────┬──────────────────┘
                            │
             simple-orchestrator-database
             ┌──────────────────────────────┐
             │  OrchestratorDB              │
             │  agents / queue / sessions   │
             │  mcps / events / heartbeats  │
             └──────────────┬───────────────┘
                            │
                       ┌─────────┐
                       │ SQLite  │
                       └─────────┘
```

### Package communication flow

```
  simple-orchestrator-core  ◄── imported by ALL other packages
  │
  ├── models/          Pydantic v2 (SessionRecord, QueueItem, AgentRecord,
  │                                 McpRecord, EventRecord, ...)
  ├── interfaces.py    IOrchestratorRepository, IOrchestratorClient (Protocols)
  ├── api.py           Request/Response Pydantic models (shared with api-client)
  ├── settings.py      WebApiSettings, WorkerSettings, TuiSettings
  ├── schedule.py      compute_next_run() — next-run calculation (interval/cron)
  └── validators.py    ValidULID, ValidWorkdir, ValidAgentId, ...

  simple-orchestrator-database
  └── OrchestratorDB  implements IOrchestratorRepository (SQLite/SQLModel)

  simple-orchestrator-api-client
  └── OrchestratorApiClient  HTTP client; implements IOrchestratorClient

  simple-orchestrator-webapi
  ├── FastAPI routes  delegates to OrchestratorDB (from database package)
  └── session_config_builder  builds SessionConfig from agent + global MCPs in DB

  simple-orchestrator-worker
  ├── QueueRunner     dequeue/dispatch with concurrency control
  ├── EventScheduler  schedules periodic events (interval or cron) via internal loop
  ├── vendors/base    BaseVendor ABC
  ├── vendors/claude_code
  ├── vendors/opencode
  ├── vendors/copilot
  └── vendors/jules

  simple-orchestrator-tui
  └── Textual TUI     Queue / Agents / Events tabs; consumes REST API via api-client
```

---

## Design principles

**Core is the only package imported by everyone.** No package imports from another peer (except `database` → `core`, `webapi` → `database` + `core`, etc.). This prevents circular dependencies.

**Database-centric.** Agents, MCPs, and events are managed via the REST API and persisted in SQLite. There is no agent/MCP configuration via TOML — TOML defines infrastructure parameters only (`db_path`, port, `log_level`, etc.).

**Standalone mode = embedded worker.** Running `simple-orchestrator standalone` starts TUI with `WorkerRunner` as a Textual background task, both sharing one `OrchestratorDB` directly — no subprocess, no HTTP.

**`IOrchestratorRepository` is the injection point.** Code that reads/writes data must type against the Protocol, never against `OrchestratorDB` directly.

**`IOrchestratorClient` crosses the client boundary.** `WorkerRunner`, `ApiSessionStore`, and `OrchestratorTUI` are typed against this Protocol. Two concrete implementations exist: `StandaloneClient` (direct DB, no HTTP) and `OrchestratorApiClient` (HTTP). When adding a new cross-boundary method, add it to `IOrchestratorClient` first, then implement in both.

**Vendors are async; DB is sync.** `OrchestratorDB` uses synchronous SQLAlchemy. WebAPI wraps DB calls in `anyio.to_thread.run_sync()` to avoid blocking the event loop.

**All primary keys are ULIDs.** Time-ordered, generated at creation. Never use random UUIDs or auto-increment integers. `worker_id` in `WorkerSettings` is also a ULID, auto-generated at startup.

**No `typing.Any` for interfaces.** Always use a Protocol or concrete type so static analysis catches mismatches between modes.

---

## Tests

Each package has its own pytest configuration — always use `--package`:

```bash
# All tests for a package
uv run --package simple-orchestrator-core    pytest packages/simple-orchestrator-core/
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/
uv run --package simple-orchestrator-webapi  pytest packages/simple-orchestrator-webapi/

# Single file
uv run --package simple-orchestrator-webapi  pytest packages/simple-orchestrator-webapi/tests/test_orchestrator_db.py

# By name
uv run --package simple-orchestrator-core    pytest packages/simple-orchestrator-core/ -k test_parse_vendor

# Integration (requires vendor auth)
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/ -m integration
```

---

## Code quality

```bash
uv run ruff check .           # lint
uv run ruff check --fix .     # lint + auto-fix
uv run ruff format .          # format
uv run pyrefly check          # type check
uv run prek run --all-files   # all at once
```

---

## Adding a new package to the workspace

1. Create `packages/<name>/pyproject.toml` with `build-backend = "uv_build"`.
2. Add `"packages/<name>"` to `[tool.uv.workspace] members` in the root `pyproject.toml`.
3. Add the source in `[tool.uv.sources]` and in `dependencies` of the workspace root.
4. If the package exposes code under `pyrefly check`, add its path to `[tool.pyrefly] project_includes`.
5. Run `uv sync` (without `--frozen`) to update the lockfile.
6. Create an empty `README.md` in the package (required for the build).
