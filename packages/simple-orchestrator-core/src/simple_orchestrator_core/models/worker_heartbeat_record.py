from __future__ import annotations

from datetime import UTC, datetime

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class WorkerHeartbeatRecord(SQLModel, table=True):
    __tablename__ = "worker_heartbeats"  # type: ignore[override]

    id: str = Field(primary_key=True)
    type: str
    name: str | None = None
    last_heartbeat_at: datetime

    @field_validator("last_heartbeat_at", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
