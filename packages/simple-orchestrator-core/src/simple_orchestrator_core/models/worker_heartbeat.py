from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from simple_orchestrator_core.validators import MAX_DESCRIPTION_LENGTH, ValidULID

WorkerType = Literal["agent-worker"]


class WorkerHeartbeat(BaseModel):
    id: ValidULID
    type: WorkerType = "agent-worker"
    name: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)


class WorkerHeartbeatStatus(WorkerHeartbeat):
    last_heartbeat_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    workers: list[WorkerHeartbeatStatus] = Field(default_factory=list)
