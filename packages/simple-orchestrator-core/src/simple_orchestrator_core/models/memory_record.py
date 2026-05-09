from datetime import UTC, datetime

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class MemoryRecord(SQLModel, table=True):
    __tablename__ = "memory"  # type: ignore[override]

    id: str = Field(primary_key=True)
    agent_id: str
    description: str
    content: str
    updated_at: datetime

    @field_validator("updated_at", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
