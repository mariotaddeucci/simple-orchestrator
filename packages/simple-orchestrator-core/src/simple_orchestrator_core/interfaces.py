from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .api import (
    AgentUpsertRequest,
    EventCreateRequest,
    EventUpdateRequest,
    McpCreateRequest,
    QueueUpdateRequest,
    SessionUpdateRequest,
)
from .models.agent_record import AgentRecord
from .models.event_record import EventRecord
from .models.mcp_record import McpRecord
from .models.memory_record import MemoryRecord
from .models.queue_item import QueueItem
from .models.session import SessionRecord
from .models.worker_heartbeat import WorkerHeartbeat
from .models.worker_heartbeat_record import WorkerHeartbeatRecord


class IAgentRepository(Protocol):
    def list_agents(self) -> list[AgentRecord]: ...

    def get_agent(self, agent_id: str) -> AgentRecord | None: ...

    def upsert_agent(self, req: AgentUpsertRequest) -> AgentRecord: ...

    def delete_agent(self, agent_id: str) -> bool: ...


class IQueueRepository(Protocol):
    def enqueue(
        self,
        agent_id: str,
        prompt: str,
        workdir: str | None = None,
        depends_on: list[str] | None = None,
        item_id: str | None = None,
    ) -> QueueItem: ...

    def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[QueueItem]: ...

    def get_queue_item(self, item_id: str) -> QueueItem | None: ...

    def update_queue_item(
        self,
        item_id: str,
        *,
        status: str,
        session_id: str | None = None,
        ended_at: datetime | None = None,
        started_at: datetime | None = None,
        note: str | None = None,
    ) -> None: ...

    def update_queue_item_api(self, item_id: str, req: QueueUpdateRequest) -> QueueItem | None: ...

    def cancel_queue_item(self, item_id: str) -> None: ...

    def reset_to_pending(self, item_id: str) -> None: ...

    def add_task_note(self, item_id: str, note: str) -> bool: ...

    def has_duplicate_pending(self, agent_id: str, prompt: str) -> bool: ...

    def dequeue_next(self) -> QueueItem | None: ...

    def cleanup_old_completed_items(self, *, max_items: int = 15, max_age_days: int = 7) -> int: ...


class ISessionRepository(Protocol):
    def save_session(self, record: SessionRecord) -> None: ...

    def save(self, record: SessionRecord) -> None: ...

    def update_session_status(self, session_id: str, req: SessionUpdateRequest) -> None: ...

    def update_status(
        self,
        session_id: str,
        status: str,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None: ...

    def get_session(self, session_id: str) -> SessionRecord | None: ...

    def get(self, session_id: str) -> SessionRecord | None: ...

    def list_sessions(self, *, vendor: str | None = None, status: str | None = None) -> list[SessionRecord]: ...


class IMemoryRepository(Protocol):
    def save_memory(self, agent_id: str, description: str, content: str) -> MemoryRecord: ...

    def get_memory(self, memory_id: str) -> MemoryRecord | None: ...

    def delete_memory(self, memory_id: str) -> bool: ...

    def list_memories(self, agent_id: str | None = None) -> list[MemoryRecord]: ...


class IWorkerRepository(Protocol):
    def upsert_worker_heartbeat(self, heartbeat: WorkerHeartbeat) -> WorkerHeartbeatRecord: ...

    def list_alive_workers(self, *, ttl_seconds: float) -> list[WorkerHeartbeatRecord]: ...


class IMcpRepository(Protocol):
    def list_mcps(self, *, is_global: bool | None = None, enabled: bool | None = None) -> list[McpRecord]: ...

    def get_mcp(self, mcp_id: str) -> McpRecord | None: ...

    def upsert_mcp(self, req: McpCreateRequest) -> McpRecord: ...

    def delete_mcp(self, mcp_id: str) -> bool: ...


class IEventRepository(Protocol):
    def list_events(self, *, enabled: bool | None = None) -> list[EventRecord]: ...

    def get_event(self, event_id: str) -> EventRecord | None: ...

    def create_event(self, req: EventCreateRequest) -> EventRecord: ...

    def update_event(self, event_id: str, req: EventUpdateRequest) -> EventRecord | None: ...

    def delete_event(self, event_id: str) -> bool: ...

    def get_due_events(self) -> list[EventRecord]: ...

    def update_next_run(self, event_id: str, next_run: datetime) -> None: ...


class IOrchestratorRepository(
    IAgentRepository,
    IQueueRepository,
    ISessionRepository,
    IMemoryRepository,
    IWorkerRepository,
    IMcpRepository,
    IEventRepository,
    Protocol,
):
    def connect(self) -> None: ...

    def close(self) -> None: ...
