# CLAUDE.md (root)

Repository guide for AI agents (Claude Code / Codex CLI).

This file is **conceptual and brief**. Practical details live in each package's `CLAUDE.md`.
Note: `AGENTS.md` at the root is a symlink to this file.

## Purpose

- Orchestrate async AI agent execution in the background (multi-vendor).
- Persist queue / sessions / memory in SQLite.
- Run in **standalone** mode (SQLite direct) or **distributed** mode (WebAPI + API client).

## Architecture principles

- `simple-orchestrator-core` is the **contract**: Pydantic models, Protocols, and API shapes.
- Everything else depends on `core` — never the reverse.
- `database` implements `IOrchestratorRepository` (SQLite) and is consumed by `webapi`.
- `api-client` implements the same repository interface over HTTP so consumers work identically.
- `worker` owns execution and vendors; `tui` is a pure repository client (DB direct or HTTP).
- Agents, MCPs, and scheduled events are managed via the REST API — not config files.

```
┌──────────────────────────────────────────────────────────┐
│  simple-orchestrator-core                                │
│  Protocols, models, settings, API shapes                 │
│  Required Python ≥ 3.14                                  │
└──────────────────────────────────────────────────────────┘
                            ↓
       ┌────────────────────┼────────────────────┐
       ↓                    ↓                    ↓
  ┌──────────┐    ┌──────────────────┐    ┌──────────────┐
  │ database │    │     webapi       │    │  api-client  │
  │ (SQLite) │    │  (FastAPI REST)  │    │  (HTTP)      │
  └──────────┘    └──────────────────┘    └──────────────┘
       ↑                    ↑                    ↑
       └────────────────────┼────────────────────┘
                            ↓
       ┌────────────────────┼────────────────────┐
       ↓                    ↓                    ↓
   ┌────────┐         ┌──────────┐         ┌─────────┐
   │ worker │         │   tui    │         │   cli   │
   │(vendors│         │(Textual) │         │ (wiring)│
   └────────┘         └──────────┘         └─────────┘
```

**Deployment modes:**
- **Standalone:** `database` ↔ `worker`/`tui` (direct SQLite, no network)
- **Distributed:** `webapi` ↔ `database`; `worker`/`tui` ↔ `api-client` ↔ `webapi`

## IDs and keys

All primary keys are **ULIDs** (time-ordered, generated at creation). Never use random UUIDs or auto-increment integers. The `worker_id` in `WorkerSettings` is also a ULID, auto-generated at startup.

## Configuration

Settings load from (in order of precedence): env vars → `ORCHESTRATOR_TOML_FILE` path → `orchestrator.toml` → `pyproject.toml [tool.orchestrator]`. See `core/settings.py` for all knobs.

## Working commands

Always use `uv` (do not activate venv manually):

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format .
uv run pyrefly check
```

Run the system:

```bash
uv run simple-orchestrator tui        # standalone: spawns webapi + worker
uv run simple-orchestrator worker
uv run simple-orchestrator webapi
```

Tests run per package (each has its own `pyproject.toml`):

```bash
uv run --package simple-orchestrator-core       pytest packages/simple-orchestrator-core/
uv run --package simple-orchestrator-api-client pytest packages/simple-orchestrator-api-client/
uv run --package simple-orchestrator-webapi     pytest packages/simple-orchestrator-webapi/
uv run --package simple-orchestrator-worker     pytest packages/simple-orchestrator-worker/
```

## Package index

See also the `CLAUDE.md` inside each folder under `packages/`:

| Package | Purpose | What to do there |
|---|---|---|
| `packages/simple-orchestrator-core/` | Contract (models, settings, Protocols, API shapes) | Evolve schemas carefully; keep `webapi` and `api-client` in sync. |
| `packages/simple-orchestrator-database/` | SQLite persistence (repository implementation) | Change queries/retention/locking; guarantee atomicity and schema compatibility. |
| `packages/simple-orchestrator-webapi/` | FastAPI REST server | Thin routing layer; delegate persistence to `database`; no duplicated business logic. |
| `packages/simple-orchestrator-api-client/` | HTTP client that implements the repository | Keep parity with `webapi` + `core/api.py`; map errors/timeouts/retries. |
| `packages/simple-orchestrator-worker/` | Queue runner + vendors + event scheduler | Concurrency, cancellation, timeouts, logs; vendor integrations (Claude/OpenCode/Copilot). |
| `packages/simple-orchestrator-tui/` | Textual terminal interface | UX and flows; consume the repository only (DB direct or HTTP). |
| `packages/simple-orchestrator/` | CLI entrypoints | Subcommands (`worker`, `webapi`, `tui`), settings wiring, DI. |

## Guide maintenance

If you identify a new concept, a new invariant, or a rule that repeats:

1. Include an objective suggestion in your response for what to add to the relevant `CLAUDE.md` (root or package).
2. Cross-cutting rules → root `CLAUDE.md`, with a reference to the affected packages.
3. Package-specific rules → `packages/<pkg>/CLAUDE.md` only.

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
