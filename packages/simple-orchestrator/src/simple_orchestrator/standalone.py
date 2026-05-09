from __future__ import annotations

from datetime import datetime

import anyio
from simple_orchestrator_core.api import (
    AgentUpsertRequest,
    EnqueueRequest,
    EventCreateRequest,
    EventUpdateRequest,
    McpCreateRequest,
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
from simple_orchestrator_core.schedule import compute_next_run
from simple_orchestrator_core.session_config_builder import build_session_config
from simple_orchestrator_database.repository import OrchestratorDB


class StandaloneClient:
    """Async client backed directly by OrchestratorDB — no HTTP, no REST API."""

    def __init__(self, db: OrchestratorDB) -> None:
        self._db = db

    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.upsert_worker_heartbeat(heartbeat))

    # ── agents ───────────────────────────────────────────────────────────────

    async def list_agents(self) -> list[AgentRecord]:
        return await anyio.to_thread.run_sync(self._db.list_agents)

    async def get_agent(self, agent_id: str) -> AgentRecord:
        result = await anyio.to_thread.run_sync(lambda: self._db.get_agent(agent_id))
        if result is None:
            raise ValueError(f"Agent {agent_id!r} not found")
        return result

    async def upsert_agent(self, req: AgentUpsertRequest) -> AgentRecord:
        return await anyio.to_thread.run_sync(lambda: self._db.upsert_agent(req))

    async def delete_agent(self, agent_id: str) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.delete_agent(agent_id))

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

    async def get_queue_item(self, item_id: str) -> QueueItem:
        result = await anyio.to_thread.run_sync(lambda: self._db.get_queue_item(item_id))
        if result is None:
            raise ValueError(f"Queue item {item_id!r} not found")
        return result

    async def cancel(self, item_id: str) -> None:
        await anyio.to_thread.run_sync(lambda: self._db.cancel_queue_item(item_id))

    async def dequeue_next(self) -> QueueDequeueResponse | None:
        item = await anyio.to_thread.run_sync(self._db.dequeue_next)
        if item is None:
            return None
        agent = await self.get_agent(item.agent_id)
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

    async def list_sessions(self, *, vendor: str | None = None, status: str | None = None) -> list[SessionRecord]:
        return await anyio.to_thread.run_sync(lambda: self._db.list_sessions(vendor=vendor, status=status))

    async def get_session(self, session_id: str) -> SessionRecord:
        result = await anyio.to_thread.run_sync(lambda: self._db.get_session(session_id))
        if result is None:
            raise ValueError(f"Session {session_id!r} not found")
        return result

    # ── events ────────────────────────────────────────────────────────────────

    async def list_events(self, *, enabled: bool | None = None) -> list[EventRecord]:
        return await anyio.to_thread.run_sync(lambda: self._db.list_events(enabled=enabled))

    async def get_event(self, event_id: str) -> EventRecord:
        result = await anyio.to_thread.run_sync(lambda: self._db.get_event(event_id))
        if result is None:
            raise ValueError(f"Event {event_id!r} not found")
        return result

    async def create_event(self, req: EventCreateRequest) -> EventRecord:
        # Mirror WebAPI validation: event refers to an agent.
        await self.get_agent(req.agent_id)
        return await anyio.to_thread.run_sync(lambda: self._db.create_event(req))

    async def update_event(self, event_id: str, req: EventUpdateRequest) -> EventRecord:
        result = await anyio.to_thread.run_sync(lambda: self._db.update_event(event_id, req))
        if result is None:
            raise ValueError(f"Event {event_id!r} not found")
        return result

    async def delete_event(self, event_id: str) -> None:
        deleted = await anyio.to_thread.run_sync(lambda: self._db.delete_event(event_id))
        if not deleted:
            raise ValueError(f"Event {event_id!r} not found")

    async def trigger_event(self, event_id: str) -> QueueItem:
        event = await self.get_event(event_id)
        await self.get_agent(event.agent_id)
        item = await anyio.to_thread.run_sync(
            lambda: self._db.enqueue(agent_id=event.agent_id, prompt=event.prompt, workdir=event.workdir),
        )
        next_run = compute_next_run(
            event.schedule_type,
            interval_minutes=event.interval_minutes,
            cron_expression=event.cron_expression,
        )
        await anyio.to_thread.run_sync(lambda: self._db.update_next_run(event_id, next_run))
        return item

    # ── mcps ─────────────────────────────────────────────────────────────────

    async def list_mcps(self, *, is_global: bool | None = None, enabled: bool | None = None) -> list[McpRecord]:
        return await anyio.to_thread.run_sync(lambda: self._db.list_mcps(is_global=is_global, enabled=enabled))

    async def get_mcp(self, mcp_id: str) -> McpRecord:
        result = await anyio.to_thread.run_sync(lambda: self._db.get_mcp(mcp_id))
        if result is None:
            raise ValueError(f"MCP {mcp_id!r} not found")
        return result

    async def upsert_mcp(self, req: McpCreateRequest) -> McpRecord:
        return await anyio.to_thread.run_sync(lambda: self._db.upsert_mcp(req))

    async def delete_mcp(self, mcp_id: str) -> None:
        deleted = await anyio.to_thread.run_sync(lambda: self._db.delete_mcp(mcp_id))
        if not deleted:
            raise ValueError(f"MCP {mcp_id!r} not found")


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
