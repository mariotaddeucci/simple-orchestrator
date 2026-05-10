# simple-orchestrator

> Async multi-vendor AI agent orchestrator with task queue and scheduling persisted in SQLite, managed via REST API.

---

## What is it?

**simple-orchestrator** is a Python framework that coordinates AI agent execution (Claude Code, OpenCode, GitHub Copilot) in the background, with concurrency control and SQLite persistence.

Designed for pipelines where a "delegator" agent distributes work to specialized agents, or for automating recurring tasks (code review, audits, reports) without human intervention.

**Database-centric:** agents, MCPs, and scheduled events are created and managed via the REST API — not config files. `orchestrator.toml` defines infrastructure parameters only.

**Two execution modes:**
- **Standalone** — `simple-orchestrator standalone` starts TUI with an embedded worker sharing one SQLite database directly — no HTTP, no subprocesses.
- **Distributed** — WebAPI, worker, and TUI run as separate processes (optionally on different hosts), communicating via HTTP.

---

## Features

| Feature | Description |
|---|---|
| **Agents via API** | Create, update, and delete agents via REST (`POST /agents`). No TOML config needed. |
| **MCPs via API** | Register MCP servers (stdio/sse/http) globally or per-agent via `POST /mcps`. |
| **Task queue** | Agents queued and processed with configurable parallelism. Tasks sharing the same `workdir` are serialized automatically. |
| **Scheduled events** | Create events with fixed interval (`interval_minutes`) or cron expression (`cron_expression`). Worker fires them automatically and computes next `next_run`. |
| **Task dependencies** | A task can declare `depends_on`; it only starts after all dependencies complete. |
| **Two execution modes** | Standalone (one command, automatic subprocesses) or distributed (REST API + remote worker). |
| **Multi-vendor** | Supports `claude_code`, `opencode`, and `github_copilot` as backends. |
| **TUI** | Terminal interface with Queue, Agents, and Events tabs. Queue a task by selecting an agent from the list. |

---

## Installation

```bash
# Requires Python 3.14+
pip install simple-orchestrator

# Development
git clone https://github.com/mariotaddeucci/simple-orchestrator
cd simple-orchestrator
uv sync --frozen
uv run prek install   # install git hooks
```

---

## Configuration

`orchestrator.toml` defines infrastructure only. Agents, MCPs, and events are managed via the API.

### `orchestrator.toml` (infrastructure)

```toml
db_path             = "orchestrator.db"
logs_dir            = "logs"
log_level           = "INFO"
max_active_sessions = 4
default_task_timeout_minutes = 30.0
poll_interval_seconds = 1.0

api_key      = "change-me"
webapi_host  = "127.0.0.1"
webapi_port  = 8765
```

**Config precedence:** env vars → `ORCHESTRATOR_TOML_FILE` path → `orchestrator.toml` → `pyproject.toml [tool.orchestrator]` → defaults.

---

## Testing

Run unit tests for all packages:

```bash
uv run pytest
```

### Integration Tests

The integration tests validate the system in different modes (standalone, distributed).

**Standalone integration tests:**

```bash
uv run pytest tests/integration/standalone
```

**Vendor integration tests (incur API costs):**

```bash
uv run pytest tests/integration/vendors -m vendor_cost
```

---

### Standalone mode (recommended to start)

One command starts the TUI with an embedded worker. Both share one SQLite database directly — no HTTP, no subprocesses.

```bash
uv run simple-orchestrator standalone
```

### Distributed mode

Each process runs independently and communicates via HTTP.

```bash
# Server — REST WebAPI + centralized database
uv run simple-orchestrator webapi

# Remote worker — connects to webapi via HTTP
ORCHESTRATOR_API_URL=http://server:8765 uv run simple-orchestrator worker

# TUI — connects to existing webapi via HTTP
ORCHESTRATOR_API_URL=http://server:8765 uv run simple-orchestrator tui
```

---

## Managing resources via API

All examples assume `api_key = "change-me"` and `webapi_port = 8765`.

### Create an agent

```bash
curl -X POST http://localhost:8765/agents \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "reviewer",
    "name": "Code Reviewer",
    "vendor": "claude_code",
    "model": "claude-sonnet-4-6",
    "workdir": ".",
    "prompt": "You are a code reviewer. Analyze changes and report issues."
  }'
```

### Register a global MCP

```bash
curl -X POST http://localhost:8765/mcps \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "filesystem",
    "name": "filesystem",
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
    "is_global": true
  }'
```

### Queue a task

```bash
curl -X POST http://localhost:8765/queue \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "reviewer",
    "prompt": "Review the latest PR."
  }'
```

### Create a scheduled event

```bash
# Fixed interval: every 30 minutes
curl -X POST http://localhost:8765/events \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "periodic review",
    "agent_id": "reviewer",
    "prompt": "Review recent changes and report issues.",
    "schedule_type": "interval",
    "interval_minutes": 30
  }'

# Cron: every day at 9am
curl -X POST http://localhost:8765/events \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "daily report",
    "agent_id": "reviewer",
    "prompt": "Generate the daily report.",
    "schedule_type": "cron",
    "cron_expression": "0 9 * * *"
  }'
```

---

## Concurrency control

```toml
# orchestrator.toml
max_active_sessions = 4   # max simultaneous sessions (global)
```

Tasks targeting the same `workdir` are serialized automatically by the worker.
Per-agent timeout is configured in the `task_timeout_minutes` field when creating the agent.

---

## Implementing a custom vendor

```python
from typing import Any, AsyncIterator
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_core.models.model import ModelInfo
from simple_orchestrator_worker.vendors.base import BaseVendor


class MyVendor(BaseVendor):
    @property
    def vendor_name(self) -> str:
        return "my_vendor"

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="my-model-v1", name="My Model v1", vendor="my_vendor")]

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        yield {"type": "text", "content": "Agent response..."}

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        async for _ in self.execute_session(config):
            pass

    async def _vendor_kill(self, session_id: str) -> None:
        pass
```

---

## Command reference

```bash
uv run simple-orchestrator standalone  # TUI + embedded worker, direct SQLite (no HTTP)
uv run simple-orchestrator tui         # TUI only — connects to existing webapi via HTTP
uv run simple-orchestrator webapi      # WebAPI only — owns the SQLite DB
uv run simple-orchestrator worker      # worker only — connects to webapi via HTTP
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture details, diagrams, and development guide.
