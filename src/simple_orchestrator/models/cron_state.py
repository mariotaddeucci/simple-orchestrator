from datetime import UTC, datetime

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class CronState(SQLModel, table=True):
    __tablename__ = "cron_state"  # type: ignore[override]

    key: str = Field(primary_key=True)
    last_run: datetime

    @field_validator("last_run", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
