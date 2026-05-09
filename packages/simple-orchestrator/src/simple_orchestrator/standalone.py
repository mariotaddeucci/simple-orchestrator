from __future__ import annotations

from datetime import datetime

import anyio
from simple_orchestrator_core.api import (
    EnqueueRequest,
    EventUpdateRequest,
    QueueDequeueResponse,
    QueueUpdateRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
)
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.event_record import EventRecord
from simple_orchestrator_core.models.mcp_record import McpRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_core.models.worker_heartbeat import WorkerHeartbeat
from simple_orchestrator_database.repository import OrchestratorDB
from simple_orchestrator_worker.session_config_builder import build_session_config


class StandaloneClient:
    """Async client backed directly by OrchestratorDB — no HTTP, no REST API."""

    def __init__(self, db: OrchestratorDB) -> None:
        self._db = db

    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.upsert_worker_heartbeat(heartbeat))

    # ── agents ───────────────────────────────────────────────────────────────

    async def list_agents(self) -> list[AgentRecord]:
        return await anyio.to_thread.run_sync(self._db.list_agents)

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        return await anyio.to_thread.run_sync(lambda: self._db.get_agent(agent_id))

    # ── queue ────────────────────────────────────────────────────────────────

    async def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[QueueItem]:
        return await anyio.to_thread.run_sync(lambda: self._db.list_queue(status=status, agent_id=agent_id))

    async def enqueue(self, req: EnqueueRequest) -> QueueItem:
        return await anyio.to_thread.run_sync(lambda: self._db.enqueue(req.agent_id, req.prompt, req.workdir))

    async def update_queue_item(self, item_id: str, req: QueueUpdateRequest) -> QueueItem:
        result = await anyio.to_thread.run_sync(lambda: self._db.update_queue_item_api(item_id, req))
        if result is None:
            raise ValueError(f"Queue item {item_id!r} not found")
        return result

    async def dequeue_next(self) -> QueueDequeueResponse | None:
        item = await anyio.to_thread.run_sync(self._db.dequeue_next)
        if item is None:
            return None
        agent = await anyio.to_thread.run_sync(lambda: self._db.get_agent(item.agent_id))
        if agent is None:
            return None
        global_mcps = await anyio.to_thread.run_sync(lambda: self._db.list_mcps(is_global=True, enabled=True))
        session_config = build_session_config(agent=agent, item=item, global_mcps=global_mcps)
        return QueueDequeueResponse(
            item=item,
            vendor=agent.vendor,
            session_config=session_config,
            timeout_minutes=agent.task_timeout_minutes,
        )

    # ── sessions ─────────────────────────────────────────────────────────────

    async def create_session(self, req: SessionCreateRequest) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.save_session(req.record))

    async def update_session(self, session_id: str, req: SessionUpdateRequest) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.update_session_status(session_id, req))

    # ── events ────────────────────────────────────────────────────────────────

    async def list_events(self, *, enabled: bool | None = None) -> list[EventRecord]:
        return await anyio.to_thread.run_sync(lambda: self._db.list_events(enabled=enabled))

    async def get_event(self, event_id: str) -> EventRecord | None:
        return await anyio.to_thread.run_sync(lambda: self._db.get_event(event_id))

    async def update_event(self, event_id: str, req: EventUpdateRequest) -> EventRecord:
        result = await anyio.to_thread.run_sync(lambda: self._db.update_event(event_id, req))
        if result is None:
            raise ValueError(f"Event {event_id!r} not found")
        return result

    # ── mcps ─────────────────────────────────────────────────────────────────

    async def list_mcps(self, *, is_global: bool | None = None, enabled: bool | None = None) -> list[McpRecord]:
        return await anyio.to_thread.run_sync(lambda: self._db.list_mcps(is_global=is_global, enabled=enabled))


class StandaloneSessionStore:
    """SessionStore backed directly by OrchestratorDB — no HTTP."""

    def __init__(self, db: OrchestratorDB) -> None:
        self._db = db

    async def save(self, record: SessionRecord) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.save_session(record))

    async def update_status(
        self,
        session_id: str,
        status: str,
        *,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._db.update_status(
                session_id,
                status,
                ended_at=ended_at,
                vendor_session_id=vendor_session_id,
            ),
        )
