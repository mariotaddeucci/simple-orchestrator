from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueueItem(BaseModel):
    id: str
    agent_id: str
    prompt: str
    workdir: str | None = None
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    session_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    depends_on: list[str] = Field(default_factory=list)
