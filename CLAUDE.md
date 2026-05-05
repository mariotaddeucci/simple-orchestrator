# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands use `uv` — never activate the venv manually.

```bash
uv run python -c "..."          # run inline Python
uv run simple-orchestrator      # run CLI entrypoint (currently a stub)
uv add <package>                # add dependency
uv sync --frozen                # sync venv strictly from lock file (reproducible)
```

### Code quality

```bash
uv run ruff check .             # lint (all rules: pyflakes, isort, security, bugbear…)
uv run ruff check --fix .       # lint + auto-fix
uv run ruff format .            # format code
uv run pyrefly check            # static type checking
```

### Git hooks (prek)

```bash
uv run prek install             # install commit hooks (run once per clone)
uv run prek run --all-files     # run all hooks on every file manually
uv run prek uninstall           # remove git hooks
```

## Architecture

Multi-vendor async agent orchestrator. Three vendors supported: Claude Code (`claude_agent_sdk`), OpenCode (`opencode_ai`), GitHub Copilot (`copilot` — package `github-copilot-sdk`, module name is `copilot`).

### Vendor polymorphism

`vendors/base.py` — `BaseVendor` ABC. All vendors inherit it and implement:
- `vendor_name: str` (property)
- `_run_session(session_id, config)` — background task body
- `_vendor_kill(session_id)` — native abort/disconnect
- `execute_session(config)` — returns `AsyncIterator` for direct streaming without DB persistence
- `list_models()` — returns available `ModelInfo` list

Public interface on `BaseVendor` (not overridden by vendors):
- `run(config) -> str` — generates ULID session_id, saves `SessionRecord(status="running")` to SQLite, spawns `asyncio.Task`, returns session_id immediately
- `kill(session_id)` — cancels task, calls `_vendor_kill`, sets `status="killed"` in DB
- `wait(session_id)` — blocks until running session completes, returns `SessionRecord`

### Shared config models (`models/`)

All Pydantic v2. Used uniformly across vendors:

| Model | Purpose |
|---|---|
| `McpConfig` | Discriminated union: `McpStdioConfig | McpSseConfig | McpHttpConfig` on `type` field |
| `SkillConfig` | Named skill with optional path and enabled flag |
| `AgentConfig` | Subagent definition for Claude Code (maps to `AgentDefinition`) |
| `SessionConfig` | Full session input: prompt, model, workdir, mcp_servers, skills, agents, subagents, env, max_turns, permission_mode |
| `SessionRecord` | DB row: id, vendor, prompt, workdir, started_at, status, ended_at, vendor_session_id |
| `ModelInfo` | id, name, vendor — returned by `list_models()` |

`SessionConfig.agents` = foreground agents. `SessionConfig.subagents` = background agents. Claude Code merges both into `ClaudeAgentOptions.agents`.

### Database layer (`db/`)

Two classes, both wrap `aiosqlite`. Use as async context managers or call `connect()`/`close()` manually.

**`SessionHistoryDB`** (`db/history.py`) — base class. Manages `sessions` table. Key methods: `save()`, `update_status()`, `get()`, `list_sessions()`. SQLite file defaults to `sessions.db` in cwd.

**`OrchestratorDB`** (`db/orchestrator.py`) — extends `SessionHistoryDB`. Adds `agents` and `queue` tables. Extra methods: `register_agent()`, `get_agent()`, `list_agents()`, `delete_agent()`, `enqueue()`, `dequeue_next()`, `update_queue_item()`, `cancel_queue_item()`, `list_queue()`.

### Queue system (`queue_runner.py`)

`QueueRunner` processes `QueueItem` rows with bounded parallelism and per-workdir serialisation.

**Agent resolution order** (TOML wins):
1. `settings.agents` (from `orchestrator.toml` — versionable, checked into git)
2. `OrchestratorDB` agents table (programmatically registered at runtime)

**Concurrency rules:**
- At most `settings.max_active_sessions` items run simultaneously (asyncio semaphore).
- Items sharing the same `workdir` are serialised (per-dir `asyncio.Lock`).
- Different workdirs run freely within the semaphore limit.

Lifecycle: `start()` / `stop()` for background polling loop. `run_until_empty()` for one-shot drain.

### Configuration (`settings.py`)

`OrchestratorSettings` loads from `orchestrator.toml` (default), `pyproject.toml` under `[tool.simple-orchestrator]` section, or the path in `ORCHESTRATOR_TOML_FILE` env var. Key fields: `db_path`, `logs_dir`, `log_level`, `max_active_sessions`, `mcp_servers`, `skills`, `agents`.

**Configuration priority** (highest to lowest):
1. `orchestrator.toml` (or path from `ORCHESTRATOR_TOML_FILE` env var)
2. `pyproject.toml` (section `[tool.simple-orchestrator]`)
3. Environment variables
4. Default values

`AgentSettings` lives inside `[agents.<id>]` in the TOML. Prompt source: either inline `prompt = "..."` or `prompt_file = "path/to/prompt.md"` (exactly one required). `resolve_prompt()` reads from file if needed. Global `mcp_servers` and `skills` are merged with per-agent ones in `QueueRunner._build_session_config()`.

`setup_logging()` configures daily-rotating file handler + stream handler; idempotent.

### Vendor-specific notes

**ClaudeCodeVendor** — passes `session_id` to `ClaudeAgentOptions` so the SDK uses our ULID. MCP servers mapped from `McpConfig` → `McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig` TypedDicts. Skills flattened to `list[str]`.

**OpenCodeVendor** — HTTP client (`AsyncOpencode`). Creates a vendor session via `session.create()`, stores returned `vendor_session_id` in DB. Kill calls `session.abort(vendor_session_id)`. Constructor takes `provider_id` and `model_id` (defaults: `"anthropic"`, `"claude-sonnet-4-5"`).

**GithubCopilotVendor** — spawns CLI subprocess via `CopilotClient`. Session handle stored in `_active_handles` for abort. Kill calls `session.abort()` then `session.disconnect()` via context manager exit.
