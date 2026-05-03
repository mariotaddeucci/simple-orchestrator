from datetime import datetime

from pydantic import BaseModel


class AgentRecord(BaseModel):
    id: str
    name: str
    nickname: str | None = None
    prompt: str
    model: str | None = None
    vendor: str
    workdir: str | None = None
    created_at: datetime
