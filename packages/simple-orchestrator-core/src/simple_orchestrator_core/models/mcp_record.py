from datetime import UTC, datetime
from typing import Literal

from pydantic import field_validator
from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class McpRecord(SQLModel, table=True):
    __tablename__ = "mcps"  # type: ignore[override]

    id: str = Field(primary_key=True)
    name: str
    type: Literal["stdio", "sse", "http"]

    # stdio
    command: str | None = None
    args: list = Field(default_factory=list, sa_column=Column(JSON, nullable=True))
    env: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=True))

    # sse / http
    url: str | None = None
    headers: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=True))

    is_global: bool = True
    enabled: bool = True
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_utc(cls, v: object) -> object:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
