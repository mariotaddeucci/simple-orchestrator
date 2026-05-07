from datetime import UTC, datetime

from pydantic import field_validator
from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class QueueItem(SQLModel, table=True):
    __tablename__ = "queue"  # type: ignore[override]

    id: str = Field(primary_key=True)
    agent_id: str
    prompt: str
    workdir: str | None = None
    status: str = "pending"
    session_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    depends_on: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=True))
    note: str | None = None

    @field_validator("created_at", "started_at", "ended_at", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @field_validator("depends_on", mode="before")
    @classmethod
    def _coerce_depends_on(cls, v: object) -> object:
        """Coerce None to empty list for backwards compatibility with old DB rows."""
        if v is None:
            return []
        return v
