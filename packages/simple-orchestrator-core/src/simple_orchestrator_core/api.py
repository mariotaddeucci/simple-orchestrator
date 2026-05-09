from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .models.agent_record import AgentRecord
from .models.queue_item import QueueItem
from .models.session import SessionConfig, SessionRecord
from .vendor_selector import normalize_vendor_id, parse_vendor_model_selection

API_KEY_HEADER = "X-API-Key"


def auth_headers(api_key: str) -> dict[str, str]:
    return {API_KEY_HEADER: api_key}


class EnqueueRequest(BaseModel):
    agent_id: str
    prompt: str
    workdir: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    item_id: str | None = None


class EnqueueResponse(BaseModel):
    item: QueueItem


class QueueListResponse(BaseModel):
    items: list[QueueItem]


class QueueUpdateRequest(BaseModel):
    status: (
        Literal[
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            "killed",
        ]
        | None
    ) = None
    session_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    note: str | None = None


class QueueDequeueResponse(BaseModel):
    item: QueueItem
    vendor: str
    timeout_minutes: float | None = None
    session_config: SessionConfig


class AgentListResponse(BaseModel):
    agents: list[AgentRecord]


class AgentUpsertRequest(BaseModel):
    id: str
    name: str
    nickname: str | None = None
    vendor: str | None = None
    model: str | None = None
    workdir: str | None = None
    task_timeout_minutes: float | None = None
    prompt: str
    mcp_servers: dict = Field(default_factory=dict)
    skills: list = Field(default_factory=list)
    skill_globs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_vendor_model_selection(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        raw_vendor = data.get("vendor")
        raw_model = data.get("model")

        if isinstance(raw_vendor, str):
            raw_vendor = raw_vendor.strip()
        if isinstance(raw_model, str):
            raw_model = raw_model.strip()

        if isinstance(raw_vendor, str) and "/" in raw_vendor and not raw_model:
            selection = parse_vendor_model_selection(raw_vendor)
            data["vendor"] = selection.vendor
            data["model"] = selection.model
            return data

        if not raw_vendor and isinstance(raw_model, str) and "/" in raw_model:
            selection = parse_vendor_model_selection(raw_model)
            data["vendor"] = selection.vendor
            data["model"] = selection.model
            return data

        if isinstance(raw_vendor, str):
            data["vendor"] = normalize_vendor_id(raw_vendor)
        return data

    @model_validator(mode="after")
    def _require_vendor(self) -> AgentUpsertRequest:
        if not self.vendor:
            raise ValueError("AgentUpsertRequest requires a vendor (or a combined provider/model selection)")
        return self


class SessionListResponse(BaseModel):
    sessions: list[SessionRecord]


class SessionCreateRequest(BaseModel):
    record: SessionRecord


class SessionUpdateRequest(BaseModel):
    status: str
    ended_at: datetime | None = None
    vendor_session_id: str | None = None
