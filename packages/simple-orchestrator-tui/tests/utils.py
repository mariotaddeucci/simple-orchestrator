from __future__ import annotations

import time
from collections.abc import Callable

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
from simple_orchestrator_core.interfaces import IOrchestratorClient
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.event_record import EventRecord
from simple_orchestrator_core.models.mcp_record import McpRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_core.models.worker_heartbeat import WorkerHeartbeat
from simple_orchestrator_core.session_config_builder import build_session_config
from simple_orchestrator_database import OrchestratorDB


class InProcessOrchestratorClient(IOrchestratorClient):
    """Test-only async adapter around OrchestratorDB for Textual integration tests."""

    def __init__(self, db: OrchestratorDB) -> None:
        self._db = db

    async def send_heartbeat(self, _heartbeat: WorkerHeartbeat) -> None:
        return None

    # agents
    async def list_agents(self) -> list[AgentRecord]:
        return self._db.list_agents()

    async def get_agent(self, agent_id: str) -> AgentRecord:
        agent = self._db.get_agent(agent_id)
        if agent is None:
            raise KeyError(agent_id)
        return agent

    async def upsert_agent(self, req: AgentUpsertRequest) -> AgentRecord:
        return self._db.upsert_agent(req)

    async def delete_agent(self, agent_id: str) -> None:
        self._db.delete_agent(agent_id)

    # queue
    async def enqueue(self, req: EnqueueRequest) -> QueueItem:
        return self._db.enqueue(agent_id=req.agent_id, prompt=req.prompt, workdir=req.workdir)

    async def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[QueueItem]:
        return self._db.list_queue(status=status, agent_id=agent_id)

    async def get_queue_item(self, item_id: str) -> QueueItem:
        item = self._db.get_queue_item(item_id)
        if item is None:
            raise KeyError(item_id)
        return item

    async def update_queue_item(self, item_id: str, req: QueueUpdateRequest) -> QueueItem:
        item = self._db.update_queue_item_api(item_id, req)
        if item is None:
            raise KeyError(item_id)
        return item

    async def cancel(self, item_id: str) -> None:
        self._db.cancel_queue_item(item_id)

    async def dequeue_next(self) -> QueueDequeueResponse | None:
        item = self._db.dequeue_next()
        if item is None:
            return None
        agent = self._db.get_agent(item.agent_id)
        assert agent is not None
        global_mcps = self._db.list_mcps(is_global=True, enabled=True)
        session_config = build_session_config(agent=agent, item=item, global_mcps=global_mcps)
        return QueueDequeueResponse(
            item=item,
            vendor=agent.vendor,
            timeout_minutes=agent.task_timeout_minutes,
            session_config=session_config,
        )

    # sessions
    async def create_session(self, req: SessionCreateRequest) -> None:
        self._db.save_session(req.record)

    async def update_session(self, session_id: str, req: SessionUpdateRequest) -> None:
        self._db.update_session_status(session_id, req)

    async def list_sessions(self, *, vendor: str | None = None, status: str | None = None) -> list[SessionRecord]:
        return self._db.list_sessions(vendor=vendor, status=status)

    async def get_session(self, session_id: str) -> SessionRecord:
        record = self._db.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        return record

    # mcps
    async def list_mcps(self, *, is_global: bool | None = None, enabled: bool | None = None) -> list[McpRecord]:
        return self._db.list_mcps(is_global=is_global, enabled=enabled)

    async def get_mcp(self, mcp_id: str) -> McpRecord:
        mcp = self._db.get_mcp(mcp_id)
        if mcp is None:
            raise KeyError(mcp_id)
        return mcp

    async def upsert_mcp(self, req: McpCreateRequest) -> McpRecord:
        return self._db.upsert_mcp(req)

    async def delete_mcp(self, mcp_id: str) -> None:
        self._db.delete_mcp(mcp_id)

    # events
    async def list_events(self, *, enabled: bool | None = None) -> list[EventRecord]:
        return self._db.list_events(enabled=enabled)

    async def get_event(self, event_id: str) -> EventRecord:
        ev = self._db.get_event(event_id)
        if ev is None:
            raise KeyError(event_id)
        return ev

    async def create_event(self, req: EventCreateRequest) -> EventRecord:
        return self._db.create_event(req)

    async def update_event(self, event_id: str, req: EventUpdateRequest) -> EventRecord:
        ev = self._db.update_event(event_id, req)
        if ev is None:
            raise KeyError(event_id)
        return ev

    async def delete_event(self, event_id: str) -> None:
        self._db.delete_event(event_id)

    async def trigger_event(self, event_id: str) -> QueueItem:
        ev = self._db.get_event(event_id)
        if ev is None:
            raise KeyError(event_id)
        return self._db.enqueue(agent_id=ev.agent_id, prompt=ev.prompt, workdir=ev.workdir)


async def wait_until(
    pilot: object,
    condition: Callable[[], bool],
    *,
    timeout_seconds: float = 5.0,
    step_seconds: float = 0.02,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return
        await pilot.pause(step_seconds)  # type: ignore[attr-defined]
    raise AssertionError("Timed out waiting for condition")
