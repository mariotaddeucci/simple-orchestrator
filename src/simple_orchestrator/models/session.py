from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .agent import AgentConfig
from .mcp import McpConfig
from .skill import SkillConfig


class SessionConfig(BaseModel):
    prompt: str
    model: str | None = None
    workdir: str = "."
    mcp_servers: dict[str, Annotated[McpConfig, Field(discriminator="type")]] = Field(default_factory=dict)
    skills: list[str | SkillConfig] = Field(default_factory=list)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    subagents: dict[str, AgentConfig] = Field(default_factory=dict)
    max_turns: int | None = None
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"] | None = None
    env: dict[str, str] = Field(default_factory=dict)


class SessionRecord(BaseModel):
    id: str
    vendor: str
    prompt: str
    workdir: str
    started_at: datetime
    status: Literal["running", "completed", "killed", "failed"]
    ended_at: datetime | None = None
    vendor_session_id: str | None = None
