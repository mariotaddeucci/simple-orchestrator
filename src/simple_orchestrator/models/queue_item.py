from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class QueueItem(BaseModel):
    id: str
    agent_id: str
    agent_nickname: str | None = None
    prompt: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    session_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
