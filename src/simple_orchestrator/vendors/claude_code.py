from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import query
from claude_agent_sdk.types import (
    AgentDefinition,
    ClaudeAgentOptions,
    McpHttpServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
)

from ..db.history import SessionHistoryDB
from ..models.agent import AgentConfig
from ..models.mcp import McpConfig, McpHttpConfig, McpSseConfig, McpStdioConfig
from ..models.model import ModelInfo
from ..models.session import SessionConfig
from ..models.skill import SkillConfig
from .base import BaseVendor

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
        options = self._build_options(config, session_id=session_id)
        async for _ in await query(prompt=config.prompt, options=options):
            pass

    async def _vendor_kill(self, session_id: str) -> None:
        pass

    def _build_options(
        self, config: SessionConfig, session_id: str | None = None
    ) -> ClaudeAgentOptions:
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
) -> dict[str, McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig]:
    result: dict[str, McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig] = {}
    for name, cfg in mcp_servers.items():
        if isinstance(cfg, McpStdioConfig):
            entry: McpStdioServerConfig = {"command": cfg.command}
            if cfg.args:
                entry["args"] = cfg.args
            if cfg.env:
                entry["env"] = cfg.env
            result[name] = entry
        elif isinstance(cfg, McpSseConfig):
            result[name] = McpSSEServerConfig(url=cfg.url)
        elif isinstance(cfg, McpHttpConfig):
            result[name] = McpHttpServerConfig(url=cfg.url)
    return result


def _map_skills(skills: list[str | SkillConfig]) -> list[str]:
    return [s if isinstance(s, str) else s.name for s in skills if isinstance(s, str) or s.enabled]


def _map_agents(agents: dict[str, AgentConfig]) -> dict[str, AgentDefinition]:
    return {
        name: AgentDefinition(
            description=cfg.description,
            prompt=cfg.prompt,
            tools=cfg.tools,
            disallowedTools=cfg.disallowed_tools,
            model=cfg.model,
            skills=cfg.skills,
            mcpServers=cfg.mcp_servers,
            initialPrompt=cfg.initial_prompt,
            maxTurns=cfg.max_turns,
            background=cfg.background,
            effort=cfg.effort,
            permissionMode=cfg.permission_mode,
        )
        for name, cfg in agents.items()
    }
