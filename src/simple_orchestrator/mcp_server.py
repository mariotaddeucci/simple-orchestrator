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
import logging
from collections.abc import Callable
from functools import cache
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from ulid import ULID

from .db.orchestrator import OrchestratorDB
from .prompts import get_prompt_content, list_prompt_names, parse_prompt_metadata
from .settings import OrchestratorSettings
from .validators import (
    MAX_DESCRIPTION_LENGTH,
    MAX_MEMORY_CONTENT_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_PROMPT_LENGTH,
    ValidAgentId,
    ValidAlias,
    ValidDepRef,
    ValidULID,
    ValidWorkdir,
)

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


def _register_prompts() -> None:
    """Register all prompts from the prompts/ directory dynamically."""
    logger = logging.getLogger(__name__)

    for prompt_name in list_prompt_names():
        try:
            content = get_prompt_content(prompt_name)
            title, description = parse_prompt_metadata(content)

            # Use title from metadata or fallback to filename
            display_name = title or prompt_name.replace("-", " ").title()

            # Create a closure to capture the content for this specific prompt
            def make_prompt_function(prompt_content: str) -> Callable[[], str]:
                def prompt_function() -> str:
                    return prompt_content

                return prompt_function

            # Register the prompt with MCP
            prompt_fn = make_prompt_function(content)
            prompt_fn.__name__ = prompt_name.replace("-", "_")
            mcp.prompt(
                prompt_fn,
                name=prompt_name,
                description=description or f"Prompt template: {display_name}",
            )
        except Exception as e:
            # Log but don't fail if a single prompt can't be loaded
            logger.warning(f"Failed to register prompt {prompt_name!r}: {e}")


# Register all prompts at module load time
_register_prompts()


def _prompt_description(prompt: str) -> str:
    """Extract a short description from a prompt string."""
    for raw_line in prompt.splitlines():
        stripped = raw_line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:200]
    return ""


async def _build_agent_nickname_map() -> dict[str, str | None]:
    """Return a mapping of agent_id -> nickname from config agents only."""
    settings = _get_settings()
    return {aid: a.nickname for aid, a in settings.agents.items()}


async def _get_agent_nickname(agent_id: str) -> str | None:
    """Return the nickname for a single agent from config only."""
    settings = _get_settings()
    if agent_id in settings.agents:
        return settings.agents[agent_id].nickname
    return None


@mcp.tool()
async def list_agents(
    vendor: Annotated[
        Literal["claude_code", "opencode", "github_copilot"] | None,
        Field(description="Filter by vendor: claude_code, opencode, github_copilot"),
    ] = None,
) -> str:
    """List all available agents that can process tasks.

    Returns id, name, vendor, workdir, and a description extracted from the agent's prompt.
    """
    settings = _get_settings()

    results: list[dict] = []

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
            },
        )

    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def enqueue_task(
    agent_id: Annotated[
        ValidAgentId,
        Field(description="ID of the agent to handle this task (use list_agents to find valid IDs)"),
    ],
    prompt: Annotated[str, Field(description="Full task description for the agent", max_length=MAX_PROMPT_LENGTH)],
    depends_on: Annotated[
        list[ValidULID] | None,
        Field(
            description="Optional list of task IDs that must complete successfully before this task starts. "
            "The task will be skipped until all listed tasks reach 'completed' status. "
            "If any dependency fails or is cancelled, this task is automatically failed too.",
            max_length=100,
        ),
    ] = None,
) -> str:
    """Add a task to the queue for a specific agent. Returns the task ID and initial status."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        item = await db.enqueue(agent_id, prompt, depends_on=depends_on)
        agent_nickname = await _get_agent_nickname(agent_id)
    return json.dumps(
        {
            "task_id": item.id,
            "agent_id": item.agent_id,
            "agent_nickname": agent_nickname,
            "status": item.status,
            "depends_on": item.depends_on,
            "created_at": item.created_at.isoformat(),
        },
    )


class _TaskSpec(BaseModel):
    alias: Annotated[
        ValidAlias | None,
        Field(
            default=None,
            description=(
                "Local name for this task — other tasks in the same batch can reference it in their depends_on list"
            ),
        ),
    ] = None
    agent_id: Annotated[ValidAgentId, Field(description="ID of the agent to handle this task")]
    prompt: Annotated[
        str,
        Field(description="Full task description for the agent", max_length=MAX_PROMPT_LENGTH),
    ]
    workdir: Annotated[
        ValidWorkdir,
        Field(default=None, description="Optional working directory override"),
    ] = None
    depends_on: Annotated[
        list[ValidDepRef],
        Field(
            default_factory=list,
            description="Aliases (from this batch) or existing task IDs this task must wait for",
            max_length=100,
        ),
    ] = Field(default_factory=list)


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
            ),
            min_length=1,
            max_length=100,
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
                },
            )

    return json.dumps({"enqueued": enqueued}, indent=2)


@mcp.tool()
async def list_tasks(
    status: Annotated[
        Literal["pending", "running", "completed", "failed", "cancelled"] | None,
        Field(description="Filter by status: pending, running, completed, failed, cancelled"),
    ] = None,
    agent_id: Annotated[ValidAgentId | None, Field(description="Filter by agent ID")] = None,
) -> str:
    """List tasks in the queue. Returns task IDs, statuses, linked session IDs, and timestamps."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        items = await db.list_queue(status=status, agent_id=agent_id)
        agent_nicknames = await _build_agent_nickname_map()

    results = []
    for item in items:
        prompt_preview = item.prompt[:150] + "…" if len(item.prompt) > 150 else item.prompt
        results.append(
            {
                "task_id": item.id,
                "agent_id": item.agent_id,
                "agent_nickname": agent_nicknames.get(item.agent_id),
                "prompt_preview": prompt_preview,
                "status": item.status,
                "depends_on": item.depends_on,
                "session_id": item.session_id,
                "note": item.note,
                "created_at": item.created_at.isoformat(),
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "ended_at": item.ended_at.isoformat() if item.ended_at else None,
            },
        )
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_task(
    task_id: Annotated[ValidULID, Field(description="Task ID returned by enqueue_task or list_tasks")],
) -> str:
    """Get full details of a specific task including its complete prompt and linked session ID."""
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        item = await db.get_queue_item(task_id)
        if not item:
            return json.dumps({"error": f"Task {task_id!r} not found"})
        agent_nickname = await _get_agent_nickname(item.agent_id)

    return json.dumps(
        {
            "task_id": item.id,
            "agent_id": item.agent_id,
            "agent_nickname": agent_nickname,
            "prompt": item.prompt,
            "status": item.status,
            "depends_on": item.depends_on,
            "session_id": item.session_id,
            "note": item.note,
            "created_at": item.created_at.isoformat(),
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "ended_at": item.ended_at.isoformat() if item.ended_at else None,
        },
    )


@mcp.tool()
async def cancel_task(
    task_id: Annotated[ValidULID, Field(description="Task ID to cancel (only works on pending tasks)")],
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
        },
    )


@mcp.tool()
async def get_session(
    session_id: Annotated[ValidULID, Field(description="Session ID from a completed task's session_id field")],
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
        },
    )


@mcp.tool()
async def add_task_note(
    task_id: Annotated[
        ValidULID,
        Field(description="Task ID to attach the note to (available in ORCHESTRATOR_TASK_ID env var)"),
    ],
    note: Annotated[
        str,
        Field(
            description="Short summary of what was done in this session and whether the objective was achieved",
            max_length=MAX_NOTE_LENGTH,
        ),
    ],
) -> str:
    """Attach a summary note to a task after completing it.

    Call this at the end of your session to record what was accomplished and whether
    the objective was fully achieved. The note is stored alongside the task and can
    be retrieved later via get_task or list_tasks to evaluate outcomes.

    The task ID is available in the ORCHESTRATOR_TASK_ID environment variable.
    """
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        found = await db.add_task_note(task_id, note)
    if not found:
        return json.dumps({"error": f"Task {task_id!r} not found"})
    return json.dumps({"task_id": task_id, "note_saved": True})


@mcp.tool()
async def save_memory(
    agent_id: Annotated[ValidAgentId, Field(description="Agent ID that owns this memory")],
    description: Annotated[
        str,
        Field(
            description="One-line summary shown in list_memories (max 200 chars)",
            max_length=MAX_DESCRIPTION_LENGTH,
        ),
    ],
    content: Annotated[
        str,
        Field(
            description="Full memory content — context, state, or notes to resume from",
            max_length=MAX_MEMORY_CONTENT_LENGTH,
        ),
    ],
) -> str:
    """Save a new memory for an agent.

    Each call creates a new memory entry; use the returned memory_id for later retrieval or deletion.
    """
    settings = _get_settings()
    async with OrchestratorDB(settings.db_path) as db:
        record = await db.save_memory(agent_id, description, content)
    return json.dumps(
        {
            "memory_id": record.id,
            "agent_id": record.agent_id,
            "description": record.description,
            "updated_at": record.updated_at.isoformat(),
        },
    )


@mcp.tool()
async def list_memories(
    agent_id: Annotated[ValidAgentId | None, Field(description="Filter by agent ID (omit to list all agents)")] = None,
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
    memory_id: Annotated[ValidULID, Field(description="Memory ID returned by save_memory or list_memories")],
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
        },
    )


@mcp.tool()
async def delete_memory(
    memory_id: Annotated[ValidULID, Field(description="Memory ID to delete")],
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
