from __future__ import annotations

from pydantic import TypeAdapter

from .models.agent_record import AgentRecord
from .models.mcp import McpConfig, McpHttpConfig, McpSseConfig, McpStdioConfig
from .models.mcp_record import McpRecord
from .models.queue_item import QueueItem
from .models.session import SessionConfig

_MCP_CONFIG_ADAPTER: TypeAdapter[McpConfig] = TypeAdapter(McpConfig)


def build_session_config(
    *,
    agent: AgentRecord,
    item: QueueItem,
    global_mcps: list[McpRecord],
) -> SessionConfig:
    """Build the final SessionConfig that a worker can execute without DB access."""
    merged_mcps: dict[str, McpConfig] = {m.name: _mcp_record_to_config(m) for m in global_mcps}

    if isinstance(agent.mcp_servers, dict):
        for name, cfg in agent.mcp_servers.items():
            merged_mcps[name] = _MCP_CONFIG_ADAPTER.validate_python(cfg)

    merged_skills: list = []
    if agent.skills:
        merged_skills.extend(list(agent.skills))

    workdir = item.workdir if item.workdir is not None else agent.workdir

    return SessionConfig(
        prompt=item.prompt,
        model=agent.model,
        workdir=workdir,
        mcp_servers=merged_mcps,
        skills=merged_skills,
        env={"ORCHESTRATOR_TASK_ID": item.id},
    )


def _mcp_record_to_config(mcp: McpRecord) -> McpConfig:
    if mcp.type == "stdio":
        return McpStdioConfig(
            command=mcp.command or "",
            args=[str(x) for x in (mcp.args or [])],
            env={str(k): str(v) for k, v in (mcp.env or {}).items()},
        )
    if mcp.type == "sse":
        return McpSseConfig(
            url=mcp.url or "",
            headers={str(k): str(v) for k, v in (mcp.headers or {}).items()},
        )
    return McpHttpConfig(
        url=mcp.url or "",
        headers={str(k): str(v) for k, v in (mcp.headers or {}).items()},
    )
