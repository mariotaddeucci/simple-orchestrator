from __future__ import annotations

from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.mcp_record import McpRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionConfig


def build_session_config(
    *,
    agent: AgentRecord,
    item: QueueItem,
    global_mcps: list[McpRecord],
) -> SessionConfig:
    """Build the final SessionConfig that a worker can execute without DB access."""
    merged_mcp: dict[str, object] = {m.name: _mcp_to_dict(m) for m in global_mcps}

    agent_mcp = agent.mcp_servers or {}
    if isinstance(agent_mcp, dict):
        merged_mcp.update(agent_mcp)

    merged_skills: list = []
    if agent.skills:
        merged_skills.extend(list(agent.skills))

    workdir = item.workdir if item.workdir is not None else agent.workdir

    return SessionConfig(
        prompt=item.prompt,
        model=agent.model,
        workdir=workdir,
        mcp_servers=merged_mcp,  # type: ignore[arg-type]
        skills=merged_skills,
        env={"ORCHESTRATOR_TASK_ID": item.id},
    )


def _mcp_to_dict(mcp: McpRecord) -> dict[str, object]:
    base: dict[str, object] = {"type": mcp.type}
    if mcp.type == "stdio":
        base["command"] = mcp.command
        base["args"] = mcp.args or []
        base["env"] = mcp.env or {}
    else:
        base["url"] = mcp.url
        base["headers"] = mcp.headers or {}
    return base
