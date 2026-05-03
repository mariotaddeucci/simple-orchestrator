"""
MCP server exposing orchestrator tools to agents.

Agents use these tools to delegate tasks to other agents and read results.

Usage (stdio transport, started as subprocess by Claude Code):
    uv run simple-orchestrator mcp-server

Configure in orchestrator.toml for a specific agent:
    [agents.delegator.mcp_servers.orchestrator]
    type    = "stdio"
    command = "uv"
    args    = ["run", "simple-orchestrator", "mcp-server"]

Or globally (all agents):
    [mcp_servers.orchestrator]
    type    = "stdio"
    command = "uv"
    args    = ["run", "simple-orchestrator", "mcp-server"]
"""

import json
from functools import cache
from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from ulid import ULID

from .db.orchestrator import OrchestratorDB
from .settings import OrchestratorSettings

mcp = FastMCP(
    "simple-orchestrator",
    instructions=(
        "Tools to delegate tasks to other agents and track their execution. "
        "Use list_agents to discover available agents, enqueue_task to delegate work, "
        "list_tasks/get_task to monitor progress, and get_session for session details."
    ),
)


@cache
def _get_settings() -> OrchestratorSettings:
    return OrchestratorSettings()


def _prompt_description(prompt: str) -> str:
    """Extract a short description from a prompt string."""
    for raw_line in prompt.splitlines():
        stripped = raw_line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:200]
    return ""


@mcp.tool()
async def list_agents(
    vendor: Annotated[str | None, Field(description="Filter by vendor: claude_code, opencode, github_copilot")] = None,
) -> str:
    """List all available agents that can process tasks.

    Returns id, name, vendor, workdir, and a description extracted from the agent's prompt.
    """
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        db_agents = await db.list_agents(vendor=vendor)

    results: list[dict] = []
    seen_ids: set[str] = set()

    for agent_id, agent_settings in settings.agents.items():
        if vendor and agent_settings.vendor != vendor:
            continue
        try:
            prompt_text = agent_settings.resolve_prompt()
        except Exception:
            prompt_text = agent_settings.prompt or ""
        results.append(
            {
                "id": agent_id,
                "name": agent_settings.name,
                "nickname": agent_settings.nickname,
                "vendor": agent_settings.vendor,
                "model": agent_settings.model,
                "workdir": agent_settings.workdir,
                "description": _prompt_description(prompt_text),
                "source": "config",
            }
        )
        seen_ids.add(agent_id)

    for agent in db_agents:
        if agent.id in seen_ids:
            continue
        results.append(
            {
                "id": agent.id,
                "name": agent.name,
                "nickname": agent.nickname,
                "vendor": agent.vendor,
                "model": agent.model,
                "workdir": agent.workdir,
                "description": _prompt_description(agent.prompt),
                "source": "database",
            }
        )

    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def enqueue_task(
    agent_id: Annotated[
        str, Field(description="ID of the agent to handle this task (use list_agents to find valid IDs)")
    ],
    prompt: Annotated[str, Field(description="Full task description for the agent")],
    depends_on: Annotated[
        list[str] | None,
        Field(
            description="Optional list of task IDs that must complete successfully before this task starts. "
            "The task will be skipped until all listed tasks reach 'completed' status. "
            "If any dependency fails or is cancelled, this task is automatically failed too."
        ),
    ] = None,
) -> str:
    """Add a task to the queue for a specific agent. Returns the task ID and initial status."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        item = await db.enqueue(agent_id, prompt, depends_on=depends_on)
    return json.dumps(
        {
            "task_id": item.id,
            "agent_id": item.agent_id,
            "agent_nickname": item.agent_nickname,
            "status": item.status,
            "depends_on": item.depends_on,
            "created_at": item.created_at.isoformat(),
        }
    )


class _TaskSpec(BaseModel):
    alias: str | None = Field(
        default=None,
        description=(
            "Local name for this task — other tasks in the same batch can reference it "
            "in their depends_on list"
        ),
    )
    agent_id: str = Field(description="ID of the agent to handle this task")
    prompt: str = Field(description="Full task description for the agent")
    workdir: str | None = Field(default=None, description="Optional working directory override")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Aliases (from this batch) or existing task IDs this task must wait for",
    )


@mcp.tool()
async def enqueue_tasks(
    tasks: Annotated[
        list[_TaskSpec],
        Field(
            description=(
                "Ordered list of tasks to enqueue in a single call. "
                "Each task may declare an 'alias' and reference other tasks' aliases in 'depends_on', "
                "allowing the full dependency graph to be expressed without extra round-trips. "
                'Example: [{"alias": "fetch", "agent_id": "a1", "prompt": "Fetch data"}, '
                '{"alias": "analyze", "agent_id": "a2", "prompt": "Analyze it", '
                '"depends_on": ["fetch"]}]'
            )
        ),
    ],
) -> str:
    """Enqueue multiple tasks at once, with optional dependencies between them.

    Tasks are processed in the order provided. Each task can reference the alias of another task
    in the same batch inside its `depends_on` list, so the entire dependency graph can be submitted
    in a single tool call — no need to enqueue tasks one by one and collect IDs manually.

    Aliases are resolved to real task IDs before insertion. You may also mix aliases with
    existing task IDs (from previous enqueue_task / enqueue_tasks calls) in `depends_on`.
    """
    if not tasks:
        return json.dumps({"error": "No tasks provided", "enqueued": []})

    # Pre-generate IDs so aliases can be resolved before any DB writes.
    task_ids = [str(ULID()) for _ in tasks]
    alias_to_id: dict[str, str] = {}
    for spec, tid in zip(tasks, task_ids, strict=True):
        if spec.alias:
            if spec.alias in alias_to_id:
                return json.dumps({"error": f"Duplicate alias {spec.alias!r}", "enqueued": []})
            alias_to_id[spec.alias] = tid

    settings = _get_settings()
    enqueued = []
    async with OrchestratorDB(settings.db_path) as db:
        for spec, tid in zip(tasks, task_ids, strict=True):
            # Resolve depends_on: replace aliases with real IDs; pass through bare IDs unchanged.
            resolved_deps = [alias_to_id.get(dep, dep) for dep in spec.depends_on]

            item = await db.enqueue(
                spec.agent_id,
                spec.prompt,
                workdir=spec.workdir,
                depends_on=resolved_deps or None,
                item_id=tid,
            )
            enqueued.append(
                {
                    "alias": spec.alias,
                    "task_id": item.id,
                    "agent_id": item.agent_id,
                    "status": item.status,
                    "depends_on": item.depends_on,
                }
            )

    return json.dumps({"enqueued": enqueued}, indent=2)


@mcp.tool()
async def list_tasks(
    status: Annotated[
        str | None,
        Field(description="Filter by status: pending, running, completed, failed, cancelled"),
    ] = None,
    agent_id: Annotated[str | None, Field(description="Filter by agent ID")] = None,
) -> str:
    """List tasks in the queue. Returns task IDs, statuses, linked session IDs, and timestamps."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        items = await db.list_queue(status=status, agent_id=agent_id)

    results = []
    for item in items:
        prompt_preview = item.prompt[:150] + "…" if len(item.prompt) > 150 else item.prompt
        results.append(
            {
                "task_id": item.id,
                "agent_id": item.agent_id,
                "agent_nickname": item.agent_nickname,
                "prompt_preview": prompt_preview,
                "status": item.status,
                "depends_on": item.depends_on,
                "session_id": item.session_id,
                "created_at": item.created_at.isoformat(),
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "ended_at": item.ended_at.isoformat() if item.ended_at else None,
            }
        )
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_task(
    task_id: Annotated[str, Field(description="Task ID returned by enqueue_task or list_tasks")],
) -> str:
    """Get full details of a specific task including its complete prompt and linked session ID."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        item = await db.get_queue_item(task_id)

    if not item:
        return json.dumps({"error": f"Task {task_id!r} not found"})

    return json.dumps(
        {
            "task_id": item.id,
            "agent_id": item.agent_id,
            "agent_nickname": item.agent_nickname,
            "prompt": item.prompt,
            "status": item.status,
            "depends_on": item.depends_on,
            "session_id": item.session_id,
            "created_at": item.created_at.isoformat(),
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "ended_at": item.ended_at.isoformat() if item.ended_at else None,
        }
    )


@mcp.tool()
async def cancel_task(
    task_id: Annotated[str, Field(description="Task ID to cancel (only works on pending tasks)")],
) -> str:
    """Cancel a pending task. Has no effect on running, completed, or already-cancelled tasks."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        item_before = await db.get_queue_item(task_id)
        if not item_before:
            return json.dumps({"error": f"Task {task_id!r} not found"})
        await db.cancel_queue_item(task_id)
        item_after = await db.get_queue_item(task_id)

    return json.dumps(
        {
            "task_id": task_id,
            "previous_status": item_before.status,
            "current_status": item_after.status if item_after else "unknown",
            "cancelled": item_after.status == "cancelled" if item_after else False,
        }
    )


@mcp.tool()
async def get_session(
    session_id: Annotated[str, Field(description="Session ID from a completed task's session_id field")],
) -> str:
    """Get details of the session created for a task. Use the session_id from get_task or list_tasks."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        record = await db.get(session_id)

    if not record:
        return json.dumps({"error": f"Session {session_id!r} not found"})

    return json.dumps(
        {
            "session_id": record.id,
            "vendor": record.vendor,
            "prompt": record.prompt,
            "workdir": record.workdir,
            "status": record.status,
            "started_at": record.started_at.isoformat(),
            "ended_at": record.ended_at.isoformat() if record.ended_at else None,
            "vendor_session_id": record.vendor_session_id,
        }
    )


@mcp.tool()
async def save_memory(
    agent_id: Annotated[str, Field(description="Agent ID that owns this memory")],
    description: Annotated[str, Field(description="One-line summary shown in list_memories (max 200 chars)")],
    content: Annotated[str, Field(description="Full memory content — context, state, or notes to resume from")],
) -> str:
    """Save a new memory for an agent.

    Each call creates a new memory entry; use the returned memory_id for later retrieval or deletion.
    """
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        record = await db.save_memory(agent_id, description[:200], content)
    return json.dumps(
        {
            "memory_id": record.id,
            "agent_id": record.agent_id,
            "description": record.description,
            "updated_at": record.updated_at.isoformat(),
        }
    )


@mcp.tool()
async def list_memories(
    agent_id: Annotated[str | None, Field(description="Filter by agent ID (omit to list all agents)")] = None,
) -> str:
    """List saved memories. Returns memory_id, agent_id, description, and updated_at — no full content."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        records = await db.list_memories(agent_id=agent_id)
    return json.dumps(
        [
            {
                "memory_id": r.id,
                "agent_id": r.agent_id,
                "description": r.description,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in records
        ],
        indent=2,
    )


@mcp.tool()
async def get_memory(
    memory_id: Annotated[str, Field(description="Memory ID returned by save_memory or list_memories")],
) -> str:
    """Get the full content of a specific memory entry."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        record = await db.get_memory(memory_id)
    if not record:
        return json.dumps({"error": f"Memory {memory_id!r} not found"})
    return json.dumps(
        {
            "memory_id": record.id,
            "agent_id": record.agent_id,
            "description": record.description,
            "content": record.content,
            "updated_at": record.updated_at.isoformat(),
        }
    )


@mcp.tool()
async def delete_memory(
    memory_id: Annotated[str, Field(description="Memory ID to delete")],
) -> str:
    """Delete a specific memory entry by its ID. No-op if not found."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        deleted = await db.delete_memory(memory_id)
    return json.dumps({"memory_id": memory_id, "deleted": deleted})


def serve() -> None:
    """Start MCP server on stdio transport (called by CLI)."""
    mcp.run(transport="stdio")


async def serve_sse_async(host: str, port: int) -> None:
    """Run MCP server on SSE transport as an awaitable coroutine."""
    await mcp.run_async(transport="sse", host=host, port=port)
