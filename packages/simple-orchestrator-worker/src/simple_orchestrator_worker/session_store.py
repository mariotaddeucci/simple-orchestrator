from __future__ import annotations

from datetime import datetime
from typing import Protocol

from simple_orchestrator_core.api import SessionCreateRequest, SessionUpdateRequest
from simple_orchestrator_core.interfaces import IOrchestratorClient
from simple_orchestrator_core.models.session import SessionRecord


class SessionStore(Protocol):
    async def save(self, record: SessionRecord) -> None: ...

    async def update_status(
        self,
        session_id: str,
        status: str,
        *,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None: ...


class ApiSessionStore:
    def __init__(self, client: IOrchestratorClient) -> None:
        self._client = client

    async def save(self, record: SessionRecord) -> None:
        await self._client.create_session(SessionCreateRequest(record=record))

    async def update_status(
        self,
        session_id: str,
        status: str,
        *,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None:
        await self._client.update_session(
            session_id,
            SessionUpdateRequest(status=status, ended_at=ended_at, vendor_session_id=vendor_session_id),
        )
