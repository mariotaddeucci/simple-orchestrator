from __future__ import annotations

from typing import Any

import httpx
from simple_orchestrator_core.api import (
    AgentListResponse,
    AgentUpsertRequest,
    EnqueueRequest,
    EnqueueResponse,
    QueueDequeueResponse,
    QueueListResponse,
    QueueUpdateRequest,
    SessionCreateRequest,
    SessionListResponse,
    SessionUpdateRequest,
    auth_headers,
)
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionRecord


class OrchestratorApiClient:
    def __init__(self, base_url: str, *, api_key: str, timeout: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=auth_headers(self._api_key),
        )

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            r = await client.get("/health")
            r.raise_for_status()
            return r.json()

    # ── agents ───────────────────────────────────────────────────────────────

    async def list_agents(self) -> list[AgentRecord]:
        async with self._client() as client:
            r = await client.get("/agents")
            r.raise_for_status()
            parsed = AgentListResponse.model_validate(r.json())
            return parsed.agents

    async def get_agent(self, agent_id: str) -> AgentRecord:
        async with self._client() as client:
            r = await client.get(f"/agents/{agent_id}")
            r.raise_for_status()
            return AgentRecord.model_validate(r.json())

    async def upsert_agent(self, req: AgentUpsertRequest) -> AgentRecord:
        async with self._client() as client:
            r = await client.post("/agents", json=req.model_dump())
            r.raise_for_status()
            return AgentRecord.model_validate(r.json())

    async def delete_agent(self, agent_id: str) -> None:
        async with self._client() as client:
            r = await client.delete(f"/agents/{agent_id}")
            r.raise_for_status()

    # ── queue ────────────────────────────────────────────────────────────────

    async def enqueue(self, req: EnqueueRequest) -> QueueItem:
        async with self._client() as client:
            r = await client.post("/queue", json=req.model_dump())
            r.raise_for_status()
            parsed = EnqueueResponse.model_validate(r.json())
            return parsed.item

    async def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[QueueItem]:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if agent_id is not None:
            params["agent_id"] = agent_id
        async with self._client() as client:
            r = await client.get("/queue", params=params)
            r.raise_for_status()
            parsed = QueueListResponse.model_validate(r.json())
            return parsed.items

    async def get_queue_item(self, item_id: str) -> QueueItem:
        async with self._client() as client:
            r = await client.get(f"/queue/{item_id}")
            r.raise_for_status()
            return QueueItem.model_validate(r.json())

    async def update_queue_item(self, item_id: str, req: QueueUpdateRequest) -> QueueItem:
        async with self._client() as client:
            r = await client.patch(f"/queue/{item_id}", json=req.model_dump(exclude_none=True))
            r.raise_for_status()
            return QueueItem.model_validate(r.json())

    async def cancel(self, item_id: str) -> None:
        async with self._client() as client:
            r = await client.post(f"/queue/{item_id}/cancel")
            r.raise_for_status()

    async def dequeue_next(self) -> QueueDequeueResponse | None:
        async with self._client() as client:
            r = await client.post("/queue/dequeue")
            if r.status_code == 204:
                return None
            r.raise_for_status()
            return QueueDequeueResponse.model_validate(r.json())

    # ── sessions ─────────────────────────────────────────────────────────────

    async def list_sessions(self, *, vendor: str | None = None, status: str | None = None) -> list[SessionRecord]:
        params: dict[str, str] = {}
        if vendor is not None:
            params["vendor"] = vendor
        if status is not None:
            params["status"] = status
        async with self._client() as client:
            r = await client.get("/sessions", params=params)
            r.raise_for_status()
            parsed = SessionListResponse.model_validate(r.json())
            return parsed.sessions

    async def get_session(self, session_id: str) -> SessionRecord:
        async with self._client() as client:
            r = await client.get(f"/sessions/{session_id}")
            r.raise_for_status()
            return SessionRecord.model_validate(r.json())

    async def create_session(self, req: SessionCreateRequest) -> None:
        async with self._client() as client:
            r = await client.post("/sessions", json=req.model_dump())
            r.raise_for_status()

    async def update_session(self, session_id: str, req: SessionUpdateRequest) -> None:
        async with self._client() as client:
            r = await client.patch(f"/sessions/{session_id}", json=req.model_dump(exclude_none=True))
            r.raise_for_status()
