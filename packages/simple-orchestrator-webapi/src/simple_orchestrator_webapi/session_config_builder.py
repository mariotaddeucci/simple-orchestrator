from __future__ import annotations

from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.mcp import McpConfig
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_core.settings import WebApiSettings


def build_session_config(*, settings: WebApiSettings, agent: AgentRecord, item: QueueItem) -> SessionConfig:
    """Build the final SessionConfig that a worker can execute without DB access."""
    merged_mcp: dict[str, McpConfig] = {**settings.mcp_servers}
    agent_mcp = agent.mcp_servers or {}
    if isinstance(agent_mcp, dict):
        merged_mcp.update(agent_mcp)  # type: ignore[arg-type]

    merged_skills: list = list(settings.skills)
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
