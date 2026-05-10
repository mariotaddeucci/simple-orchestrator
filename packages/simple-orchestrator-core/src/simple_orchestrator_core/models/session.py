from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, field_validator
from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel

from .agent import AgentConfig
from .mcp import McpConfig
from .skill import SkillConfig


class SessionRecord(SQLModel, table=True):
    __tablename__ = "sessions"  # type: ignore[override]

    id: str = Field(primary_key=True)
    vendor: str
    prompt: str
    workdir: str
    started_at: datetime
    status: str
    ended_at: datetime | None = None
    vendor_session_id: str | None = None

    @field_validator("started_at", "ended_at", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class SessionConfig(BaseModel):
    prompt: str
    model: str | None = None
    workdir: str | None = None
    mcp_servers: dict[str, Annotated[McpConfig, PydanticField(discriminator="type")]] = PydanticField(
        default_factory=dict,
    )
    skills: list[str | SkillConfig] = PydanticField(default_factory=list)
    agents: dict[str, AgentConfig] = PydanticField(default_factory=dict)
    subagents: dict[str, AgentConfig] = PydanticField(default_factory=dict)
    max_turns: int | None = None
    always_open_pr: bool = False
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"] | None = None
    env: dict[str, str] = PydanticField(default_factory=dict)
