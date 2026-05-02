from datetime import datetime
from pydantic import BaseModel


class MemoryRecord(BaseModel):
    id: str
    agent_id: str
    description: str
    content: str
    updated_at: datetime
