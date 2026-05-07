from collections.abc import AsyncIterator
from typing import Any, cast

from claude_agent_sdk import query
from claude_agent_sdk.types import (
    AgentDefinition,
    ClaudeAgentOptions,
    McpHttpServerConfig,
    McpServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
)
from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.logging_config import get_vendor_logger
from simple_orchestrator.models.agent import AgentConfig
from simple_orchestrator.models.mcp import McpConfig, McpHttpConfig, McpLocalConfig, McpSseConfig, McpStdioConfig
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.session import SessionConfig
from simple_orchestrator.models.skill import SkillConfig
from simple_orchestrator.vendors.base import BaseVendor

logger = get_vendor_logger(__name__)

_CLAUDE_MODELS = [
    ModelInfo(id="claude-opus-4-7", name="Claude Opus 4.7", vendor="claude_code"),
    ModelInfo(id="claude-sonnet-4-6", name="Claude Sonnet 4.6", vendor="claude_code"),
    ModelInfo(id="claude-haiku-4-5-20251001", name="Claude Haiku 4.5", vendor="claude_code"),
    ModelInfo(id="claude-opus-4-5", name="Claude Opus 4.5", vendor="claude_code"),
    ModelInfo(id="claude-sonnet-4-5", name="Claude Sonnet 4.5", vendor="claude_code"),
    ModelInfo(id="claude-haiku-3-5", name="Claude Haiku 3.5", vendor="claude_code"),
]


class ClaudeCodeVendor(BaseVendor):
    def __init__(self, db: SessionHistoryDB, cli_path: str | None = None) -> None:
        super().__init__(db)
        self._cli_path = cli_path

    @property
    def vendor_name(self) -> str:
        return "claude_code"

    async def list_models(self) -> list[ModelInfo]:
        return list(_CLAUDE_MODELS)

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        options = self._build_options(config)
        return query(prompt=config.prompt, options=options)

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        # Claude CLI requires UUID format; convert ULID to its UUID representation
        claude_session_id = str(ULID.from_str(session_id).to_uuid())
        logger.info("Claude Code: starting session session_id=%s claude_session_id=%s", session_id, claude_session_id)
        logger.debug(
            "Claude Code config: model=%s workdir=%s mcp_servers=%d skills=%d",
            config.model,
            config.workdir,
            len(config.mcp_servers),
            len(config.skills),
        )
        options = self._build_options(config, session_id=claude_session_id)
        async for _ in query(prompt=config.prompt, options=options):
            pass
        logger.info("Claude Code: session completed session_id=%s", session_id)

    async def _vendor_kill(self, session_id: str) -> None:
        pass

    def _build_options(self, config: SessionConfig, session_id: str | None = None) -> ClaudeAgentOptions:
        all_agents = {**config.agents, **config.subagents}
        return ClaudeAgentOptions(
            model=config.model,
            cwd=config.workdir,
            mcp_servers=_map_mcp_servers(config.mcp_servers),
            skills=_map_skills(config.skills) or None,
            agents=_map_agents(all_agents) or None,
            max_turns=config.max_turns,
            permission_mode=config.permission_mode,
            env=config.env,
            cli_path=self._cli_path,
            session_id=session_id,
        )


def _map_mcp_servers(
    mcp_servers: dict[str, McpConfig],
) -> dict[str, McpServerConfig]:
    result: dict[str, McpServerConfig] = {}
    for name, cfg in mcp_servers.items():
        # Resolve local FastMCP apps to an equivalent stdio config first
        resolved = cfg.to_stdio() if isinstance(cfg, McpLocalConfig) else cfg
        if isinstance(resolved, McpStdioConfig):
            entry: McpStdioServerConfig = {"command": resolved.command}
            if resolved.args:
                entry["args"] = resolved.args
            if resolved.env:
                entry["env"] = resolved.env
            result[name] = entry
        elif isinstance(resolved, McpSseConfig):
            result[name] = McpSSEServerConfig(type="sse", url=resolved.url)
        elif isinstance(resolved, McpHttpConfig):
            result[name] = McpHttpServerConfig(type="http", url=resolved.url)
    return result


def _map_skills(skills: list[str | SkillConfig]) -> list[str]:
    return [
        s if isinstance(s, str) else (s.path if s.path is not None else s.name)
        for s in skills
        if isinstance(s, str) or s.enabled
    ]


def _map_agents(agents: dict[str, AgentConfig]) -> dict[str, AgentDefinition]:
    return {
        name: AgentDefinition(
            description=cfg.description,
            prompt=cfg.prompt,
            tools=cfg.tools,
            disallowedTools=cfg.disallowed_tools,
            model=cfg.model,
            skills=cfg.skills,
            mcpServers=cast("list[str | dict[str, Any]] | None", cfg.mcp_servers),
            initialPrompt=cfg.initial_prompt,
            maxTurns=cfg.max_turns,
            background=cfg.background,
            effort=cfg.effort,
            permissionMode=cfg.permission_mode,
        )
        for name, cfg in agents.items()
    }
