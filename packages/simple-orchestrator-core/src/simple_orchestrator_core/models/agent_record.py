from datetime import UTC, datetime

from pydantic import field_validator
from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class AgentRecord(SQLModel, table=True):
    __tablename__ = "agents"  # type: ignore[override]

    id: str = Field(primary_key=True)
    name: str
    nickname: str | None = None
    prompt: str
    model: str | None = None
    vendor: str
    workdir: str | None = None
    task_timeout_minutes: float | None = None
    # Stored as raw JSON. Interpreted by Web API when building SessionConfig.
    mcp_servers: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=True))
    skills: list = Field(default_factory=list, sa_column=Column(JSON, nullable=True))
    skill_globs: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=True))
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
