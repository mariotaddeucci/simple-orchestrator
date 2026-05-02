"""
OrchestratorSettings loads configuration from `orchestrator.toml` (default) or
the path set in the `ORCHESTRATOR_TOML_FILE` env var.

TOML structure example
──────────────────────
db_path            = "orchestrator.db"
logs_dir           = "logs"
log_level          = "INFO"       # DEBUG | INFO | WARNING | ERROR | CRITICAL
max_active_sessions = 4

[mcp_servers.filesystem]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]

[mcp_servers.github]
type = "sse"
url  = "http://localhost:3001/sse"

skills = ["my-skill", "other-skill"]

[agents.reviewer]
name     = "Code Reviewer"
nickname = "reviewer"
vendor   = "claude_code"
model    = "claude-sonnet-4-6"
workdir  = "/workspace"
prompt   = "You are an expert code reviewer..."  # inline prompt

[agents.auditor]
name        = "Security Auditor"
nickname    = "auditor"
vendor      = "claude_code"
model       = "claude-opus-4-7"
workdir     = "/workspace"
prompt_file = "prompts/security-auditor.md"   # path to markdown file

Agent prompt markdown format (prompts/security-auditor.md)
──────────────────────────────────────────────────────────
# Security Auditor

## Role
You are a security expert…

## Instructions
1. Identify OWASP Top 10 vulnerabilities
2. Check for secrets in code
3. Evaluate dependency risk

## Output format
Return findings as a markdown list grouped by severity.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .models.mcp import McpConfig
from .models.skill import SkillConfig

_TOML_FILE_ENV = "ORCHESTRATOR_TOML_FILE"


class PollingSettings(BaseModel):
    """
    Scheduled polling entry — enqueues a prompt to an agent every N minutes.
    Duplicate detection: skips enqueue if an identical (agent_id + prompt) item
    is already pending or running.

    TOML syntax (array of tables):

        [[pollings]]
        agent_id         = "reviewer"
        prompt           = "Review recent git changes and report issues."
        interval_minutes = 30
    """

    agent_id: str
    prompt: str
    interval_minutes: float = Field(gt=0)


class AgentSettings(BaseModel):
    """
    Full agent definition — lives in orchestrator.toml (versionable).

    Prompt source (exactly one must be set):
      prompt      = "inline text"
      prompt_file = "path/to/prompt.md"
    """

    name: str
    nickname: str | None = None
    vendor: str
    model: str | None = None
    workdir: str = "."
    prompt: str | None = None
    prompt_file: Path | None = None
    mcp_servers: dict[
        str,
        Annotated[McpConfig, Field(discriminator="type")],
    ] = Field(default_factory=dict)
    skills: list[str | SkillConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_prompt_source(self) -> "AgentSettings":
        has_inline = bool(self.prompt)
        has_file = self.prompt_file is not None
        if not has_inline and not has_file:
            raise ValueError("AgentSettings requires either 'prompt' or 'prompt_file'")
        if has_inline and has_file:
            raise ValueError("Set only one of 'prompt' or 'prompt_file', not both")
        return self

    def resolve_prompt(self) -> str:
        """Return the prompt text, reading from file if needed."""
        if self.prompt_file:
            return Path(self.prompt_file).read_text(encoding="utf-8").strip()
        return (self.prompt or "").strip()

    @property
    def label(self) -> str:
        return self.nickname or self.name


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTRATOR_",
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
    )

    db_path: str = "orchestrator.db"
    logs_dir: Path = Path("logs")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    max_active_sessions: int = Field(default=4, ge=1)

    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8765

    mcp_servers: dict[
        str,
        Annotated[McpConfig, Field(discriminator="type")],
    ] = Field(default_factory=dict)
    skills: list[str | SkillConfig] = Field(default_factory=list)
    agents: dict[str, AgentSettings] = Field(default_factory=dict)
    pollings: list[PollingSettings] = Field(default_factory=list)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
        ]
        toml_path = Path(os.environ.get(_TOML_FILE_ENV, "orchestrator.toml"))
        if toml_path.exists():
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_path))
        return tuple(sources)


def setup_logging(settings: OrchestratorSettings) -> None:
    """
    Configure root logger with a daily-rotating file handler + stream handler.
    Subsequent calls are idempotent (handlers not added twice).
    """
    level = logging.getLevelName(settings.log_level)
    logs_dir = Path(settings.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    # Skip if handlers already configured at this level
    existing_files = {
        h.baseFilename
        for h in root.handlers
        if isinstance(h, TimedRotatingFileHandler)
    }
    log_file = str(logs_dir / "orchestrator.log")
    if log_file not in existing_files:
        fh = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, TimedRotatingFileHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    root.setLevel(level)
