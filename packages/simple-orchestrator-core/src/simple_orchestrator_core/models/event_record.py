from datetime import UTC, datetime

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class EventRecord(SQLModel, table=True):
    __tablename__ = "events"  # type: ignore[override]

    id: str = Field(primary_key=True)
    name: str
    agent_id: str
    prompt: str
    workdir: str | None = None

    schedule_type: str  # "interval" | "cron" — validated at API layer
    interval_minutes: float | None = None
    cron_expression: str | None = None

    next_run: datetime | None = None
    enabled: bool = True

    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", "next_run", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
