from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from simple_orchestrator_core.api import (
    AgentUpsertRequest,
    EventCreateRequest,
    EventUpdateRequest,
    McpCreateRequest,
    QueueUpdateRequest,
    SessionUpdateRequest,
)
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.event_record import EventRecord
from simple_orchestrator_core.models.mcp_record import McpRecord
from simple_orchestrator_core.models.memory_record import MemoryRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_core.models.worker_heartbeat import WorkerHeartbeat
from simple_orchestrator_core.models.worker_heartbeat_record import WorkerHeartbeatRecord
from simple_orchestrator_core.schedule import compute_next_run
from sqlalchemy import select, update
from sqlmodel import Session
from ulid import ULID

from .engine import build_engine

logger = logging.getLogger(__name__)


def _new_ulid() -> str:
    return str(ULID())


def _clone[T](obj: T) -> T:
    return type(obj).model_validate(obj.model_dump())  # type: ignore[attr-defined]


def _clone_list[T](objs: list[T]) -> list[T]:
    return [_clone(o) for o in objs]


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class OrchestratorDB:
    """Direct SQLite implementation of IOrchestratorRepository."""

    def __init__(self, db_path: str | Path = "orchestrator.db") -> None:
        self._engine = build_engine(db_path)

    def __enter__(self) -> OrchestratorDB:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        """No-op: engine is created in __init__. Kept for interface compatibility."""

    def close(self) -> None:
        self._engine.dispose()

    # ── agents ───────────────────────────────────────────────────────────────

    def list_agents(self) -> list[AgentRecord]:
        with Session(self._engine) as session:
            stmt = select(AgentRecord).order_by(AgentRecord.created_at.desc())  # type: ignore[arg-type]
            return _clone_list(list(session.execute(stmt).scalars().all()))

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with Session(self._engine) as session:
            obj = session.get(AgentRecord, agent_id)
            return _clone(obj) if obj else None

    def upsert_agent(self, req: AgentUpsertRequest) -> AgentRecord:
        now = datetime.now(UTC)
        vendor = req.vendor
        assert vendor is not None
        with Session(self._engine) as session:
            obj = session.get(AgentRecord, req.id)
            if obj is None:
                obj = AgentRecord(
                    id=req.id,
                    name=req.name,
                    nickname=req.nickname,
                    prompt=req.prompt,
                    model=req.model,
                    vendor=vendor,
                    task_timeout_minutes=req.task_timeout_minutes,
                    mcp_servers=req.mcp_servers,
                    skills=req.skills,
                    skill_globs=req.skill_globs,
                    created_at=now,
                )
            else:
                obj.name = req.name
                obj.nickname = req.nickname
                obj.prompt = req.prompt
                obj.model = req.model
                obj.vendor = vendor
                obj.task_timeout_minutes = req.task_timeout_minutes
                obj.mcp_servers = req.mcp_servers
                obj.skills = req.skills
                obj.skill_globs = req.skill_globs

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return _clone(obj)

    def delete_agent(self, agent_id: str) -> bool:
        with Session(self._engine) as session:
            obj = session.get(AgentRecord, agent_id)
            if not obj:
                return False
            session.delete(obj)
            session.commit()
            return True

    # ── queue ────────────────────────────────────────────────────────────────

    def enqueue(
        self,
        agent_id: str,
        prompt: str,
        workdir: str | None = None,
        depends_on: list[str] | None = None,
        item_id: str | None = None,
    ) -> QueueItem:
        item = QueueItem(
            id=item_id or _new_ulid(),
            agent_id=agent_id,
            prompt=prompt,
            workdir=workdir,
            status="pending",
            created_at=datetime.now(UTC),
            depends_on=depends_on or [],
        )
        logger.info("DB enqueue: id=%s agent_id=%s workdir=%s", item.id, agent_id, item.workdir)
        with Session(self._engine) as session:
            session.add(item)
            session.commit()
            session.refresh(item)
            return _clone(item)

    def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[QueueItem]:
        with Session(self._engine) as session:
            stmt = select(QueueItem)
            if status is not None:
                stmt = stmt.where(QueueItem.status == status)  # type: ignore[arg-type]
            if agent_id is not None:
                stmt = stmt.where(QueueItem.agent_id == agent_id)  # type: ignore[arg-type]
            stmt = stmt.order_by(QueueItem.id)  # type: ignore[arg-type]
            return _clone_list(list(session.execute(stmt).scalars().all()))

    def get_queue_item(self, item_id: str) -> QueueItem | None:
        with Session(self._engine) as session:
            obj = session.get(QueueItem, item_id)
            return _clone(obj) if obj else None

    def update_queue_item(
        self,
        item_id: str,
        *,
        status: str,
        session_id: str | None = None,
        ended_at: datetime | None = None,
        started_at: datetime | None = None,
        note: str | None = None,
    ) -> None:
        with Session(self._engine) as session:
            item = session.get(QueueItem, item_id)
            if item:
                item.status = status
                if session_id is not None:
                    item.session_id = session_id
                if ended_at is not None:
                    item.ended_at = ended_at
                if started_at is not None:
                    item.started_at = started_at
                if note is not None:
                    item.note = note
                session.add(item)
                session.commit()

    def update_queue_item_api(self, item_id: str, req: QueueUpdateRequest) -> QueueItem | None:
        with Session(self._engine) as session:
            item = session.get(QueueItem, item_id)
            if not item:
                return None
            if req.status is not None:
                item.status = req.status
            if req.session_id is not None:
                item.session_id = req.session_id
            if req.started_at is not None:
                item.started_at = req.started_at
            if req.ended_at is not None:
                item.ended_at = req.ended_at
            if req.note is not None:
                item.note = req.note
            session.add(item)
            session.commit()
            session.refresh(item)
            return _clone(item)

    def cancel_queue_item(self, item_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(QueueItem)
                .where(QueueItem.id == item_id, QueueItem.status == "pending")  # type: ignore[arg-type]
                .values(status="cancelled", ended_at=datetime.now(UTC)),
            )
            session.commit()

    def reset_to_pending(self, item_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(QueueItem)
                .where(QueueItem.id == item_id)  # type: ignore[arg-type]
                .values(status="pending", started_at=None, session_id=None, ended_at=None),
            )
            session.commit()

    def add_task_note(self, item_id: str, note: str) -> bool:
        with Session(self._engine) as session:
            result = session.execute(update(QueueItem).where(QueueItem.id == item_id).values(note=note))  # type: ignore[arg-type]
            session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def has_duplicate_pending(self, agent_id: str, prompt: str) -> bool:
        with Session(self._engine) as session:
            row = session.execute(
                select(QueueItem)
                .where(
                    QueueItem.agent_id == agent_id,  # type: ignore[arg-type]
                    QueueItem.prompt == prompt,  # type: ignore[arg-type]
                    QueueItem.status.in_(["pending", "running"]),  # type: ignore[attr-defined]
                )
                .limit(1),
            ).first()
        return row is not None

    def dequeue_next(self) -> QueueItem | None:
        with Session(self._engine) as session:
            items = _clone_list(
                list(
                    session.execute(
                        select(QueueItem).where(QueueItem.status == "pending").order_by(QueueItem.id),  # type: ignore[arg-type]
                    )
                    .scalars()
                    .all(),
                ),
            )

        now = datetime.now(UTC)

        for item in items:
            depends = item.depends_on or []

            if not depends:
                if self._try_claim(item.id, now):
                    return self._as_running(item, now)
                continue

            dep_statuses = self._get_dep_statuses(depends)
            terminal_failed = {did for did, st in dep_statuses.items() if st in ("failed", "cancelled", "killed")}
            missing = set(depends) - set(dep_statuses)

            if terminal_failed or missing:
                with Session(self._engine) as session:
                    session.execute(
                        update(QueueItem).where(QueueItem.id == item.id).values(status="failed", ended_at=now),  # type: ignore[arg-type]
                    )
                    session.commit()
                continue

            if all(dep_statuses.get(did) == "completed" for did in depends) and self._try_claim(item.id, now):
                return self._as_running(item, now)

        return None

    def _try_claim(self, item_id: str, now: datetime) -> bool:
        with Session(self._engine) as session:
            result = session.execute(
                update(QueueItem)
                .where(QueueItem.id == item_id, QueueItem.status == "pending")  # type: ignore[arg-type]
                .values(status="running", started_at=now),
            )
            session.commit()
        claimed = result.rowcount > 0  # type: ignore[attr-defined]
        if claimed:
            logger.info("DB dequeue_next: claimed id=%s", item_id)
        return claimed

    def _as_running(self, item: QueueItem, now: datetime) -> QueueItem:
        return QueueItem(
            id=item.id,
            agent_id=item.agent_id,
            prompt=item.prompt,
            workdir=item.workdir,
            status="running",
            session_id=item.session_id,
            created_at=item.created_at,
            started_at=now,
            ended_at=item.ended_at,
            depends_on=item.depends_on or [],
            note=item.note,
        )

    def _get_dep_statuses(self, dep_ids: list[str]) -> dict[str, str]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(QueueItem.id, QueueItem.status).where(QueueItem.id.in_(dep_ids)),  # type: ignore[attr-defined]
            ).all()
        return {row[0]: row[1] for row in rows}

    def cleanup_old_completed_items(self, *, max_items: int = 15, max_age_days: int = 7) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        with Session(self._engine) as session:
            completed = list(
                session.execute(
                    select(QueueItem)
                    .where(QueueItem.status == "completed")  # type: ignore[arg-type]
                    .order_by(QueueItem.ended_at.desc()),  # type: ignore[arg-type]
                )
                .scalars()
                .all(),
            )
            old_by_age = [it for it in completed if it.ended_at and _as_utc(it.ended_at) < cutoff]
            old_by_count = completed[max_items:] if len(completed) > max_items else []
            to_delete = {it.id for it in old_by_age + old_by_count}
            if not to_delete:
                return 0
            for it in completed:
                if it.id in to_delete:
                    session.delete(it)
            session.commit()
            return len(to_delete)

    # ── sessions ─────────────────────────────────────────────────────────────

    def save_session(self, record: SessionRecord) -> None:
        with Session(self._engine) as session:
            session.merge(record)
            session.commit()

    def save(self, record: SessionRecord) -> None:
        self.save_session(record)

    def update_session_status(self, session_id: str, req: SessionUpdateRequest) -> None:
        with Session(self._engine) as session:
            record = session.get(SessionRecord, session_id)
            if record:
                record.status = req.status
                if req.ended_at is not None:
                    record.ended_at = req.ended_at
                if req.vendor_session_id is not None:
                    record.vendor_session_id = req.vendor_session_id
                session.add(record)
                session.commit()

    def update_status(
        self,
        session_id: str,
        status: str,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None:
        self.update_session_status(
            session_id,
            SessionUpdateRequest(status=status, ended_at=ended_at, vendor_session_id=vendor_session_id),
        )

    def get_session(self, session_id: str) -> SessionRecord | None:
        with Session(self._engine) as session:
            obj = session.get(SessionRecord, session_id)
            return _clone(obj) if obj else None

    def get(self, session_id: str) -> SessionRecord | None:
        return self.get_session(session_id)

    def list_sessions(self, *, vendor: str | None = None, status: str | None = None) -> list[SessionRecord]:
        with Session(self._engine) as session:
            stmt = select(SessionRecord)
            if vendor is not None:
                stmt = stmt.where(SessionRecord.vendor == vendor)  # type: ignore[arg-type]
            if status is not None:
                stmt = stmt.where(SessionRecord.status == status)  # type: ignore[arg-type]
            stmt = stmt.order_by(SessionRecord.started_at.desc())  # type: ignore[arg-type]
            return _clone_list(list(session.execute(stmt).scalars().all()))

    # ── memory ────────────────────────────────────────────────────────────────

    def save_memory(self, agent_id: str, description: str, content: str) -> MemoryRecord:
        record = MemoryRecord(
            id=_new_ulid(),
            agent_id=agent_id,
            description=description,
            content=content,
            updated_at=datetime.now(UTC),
        )
        with Session(self._engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return _clone(record)

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        with Session(self._engine) as session:
            obj = session.get(MemoryRecord, memory_id)
            return _clone(obj) if obj else None

    def delete_memory(self, memory_id: str) -> bool:
        with Session(self._engine) as session:
            record = session.get(MemoryRecord, memory_id)
            if not record:
                return False
            session.delete(record)
            session.commit()
        return True

    def list_memories(self, agent_id: str | None = None) -> list[MemoryRecord]:
        with Session(self._engine) as session:
            stmt = select(MemoryRecord)
            if agent_id:
                stmt = stmt.where(MemoryRecord.agent_id == agent_id)  # type: ignore[arg-type]
            stmt = stmt.order_by(MemoryRecord.updated_at.desc())  # type: ignore[arg-type]
            return _clone_list(list(session.execute(stmt).scalars().all()))

    # ── workers ───────────────────────────────────────────────────────────────

    def upsert_worker_heartbeat(self, heartbeat: WorkerHeartbeat) -> WorkerHeartbeatRecord:
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            record = session.get(WorkerHeartbeatRecord, heartbeat.id)
            if record is None:
                record = WorkerHeartbeatRecord(
                    id=heartbeat.id,
                    type=heartbeat.type,
                    name=heartbeat.name,
                    last_heartbeat_at=now,
                )
            else:
                record.type = heartbeat.type
                record.name = heartbeat.name
                record.last_heartbeat_at = now
            session.add(record)
            session.commit()
            session.refresh(record)
            return _clone(record)

    def list_alive_workers(self, *, ttl_seconds: float) -> list[WorkerHeartbeatRecord]:
        cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
        with Session(self._engine) as session:
            stmt = (
                select(WorkerHeartbeatRecord)
                .where(WorkerHeartbeatRecord.last_heartbeat_at >= cutoff)  # type: ignore[arg-type]
                .order_by(WorkerHeartbeatRecord.last_heartbeat_at.desc())  # type: ignore[arg-type]
            )
            return _clone_list(list(session.execute(stmt).scalars().all()))

    # ── mcps ─────────────────────────────────────────────────────────────────

    def list_mcps(self, *, is_global: bool | None = None, enabled: bool | None = None) -> list[McpRecord]:
        with Session(self._engine) as session:
            stmt = select(McpRecord).order_by(McpRecord.created_at.desc())  # type: ignore[arg-type]
            results = _clone_list(list(session.execute(stmt).scalars().all()))
        if is_global is not None:
            results = [m for m in results if m.is_global == is_global]
        if enabled is not None:
            results = [m for m in results if m.enabled == enabled]
        return results

    def get_mcp(self, mcp_id: str) -> McpRecord | None:
        with Session(self._engine) as session:
            obj = session.get(McpRecord, mcp_id)
            return _clone(obj) if obj else None

    def upsert_mcp(self, req: McpCreateRequest) -> McpRecord:
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            obj = session.get(McpRecord, req.id)
            if obj is None:
                obj = McpRecord(
                    id=req.id,
                    name=req.name,
                    type=req.type,
                    command=req.command,
                    args=req.args,
                    env=req.env,
                    url=req.url,
                    headers=req.headers,
                    is_global=req.is_global,
                    enabled=req.enabled,
                    created_at=now,
                )
            else:
                obj.name = req.name
                obj.type = req.type
                obj.command = req.command
                obj.args = req.args
                obj.env = req.env
                obj.url = req.url
                obj.headers = req.headers
                obj.is_global = req.is_global
                obj.enabled = req.enabled
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return _clone(obj)

    def delete_mcp(self, mcp_id: str) -> bool:
        with Session(self._engine) as session:
            obj = session.get(McpRecord, mcp_id)
            if not obj:
                return False
            session.delete(obj)
            session.commit()
            return True

    # ── events ────────────────────────────────────────────────────────────────

    def list_events(self, *, enabled: bool | None = None) -> list[EventRecord]:
        with Session(self._engine) as session:
            stmt = select(EventRecord).order_by(EventRecord.created_at.desc())  # type: ignore[arg-type]
            results = _clone_list(list(session.execute(stmt).scalars().all()))
        if enabled is not None:
            results = [e for e in results if e.enabled == enabled]
        return results

    def get_event(self, event_id: str) -> EventRecord | None:
        with Session(self._engine) as session:
            obj = session.get(EventRecord, event_id)
            return _clone(obj) if obj else None

    def create_event(self, req: EventCreateRequest) -> EventRecord:
        now = datetime.now(UTC)
        next_run = compute_next_run(
            req.schedule_type,
            interval_minutes=req.interval_minutes,
            cron_expression=req.cron_expression,
            base=now,
        )
        record = EventRecord(
            id=_new_ulid(),
            name=req.name,
            agent_id=req.agent_id,
            prompt=req.prompt,
            workdir=req.workdir,
            schedule_type=req.schedule_type,
            interval_minutes=req.interval_minutes,
            cron_expression=req.cron_expression,
            next_run=next_run,
            enabled=req.enabled,
            created_at=now,
            updated_at=now,
        )
        with Session(self._engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return _clone(record)

    def update_event(self, event_id: str, req: EventUpdateRequest) -> EventRecord | None:
        now = datetime.now(UTC)
        fields = req.model_dump(exclude_none=True)
        with Session(self._engine) as session:
            obj = session.get(EventRecord, event_id)
            if not obj:
                return None
            for k, v in fields.items():
                setattr(obj, k, v)
            obj.updated_at = now
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return _clone(obj)

    def delete_event(self, event_id: str) -> bool:
        with Session(self._engine) as session:
            obj = session.get(EventRecord, event_id)
            if not obj:
                return False
            session.delete(obj)
            session.commit()
            return True

    def get_due_events(self) -> list[EventRecord]:
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            stmt = (
                select(EventRecord)
                .where(EventRecord.next_run <= now)  # type: ignore[arg-type]
                .order_by(EventRecord.next_run)  # type: ignore[arg-type]
            )
            results = _clone_list(list(session.execute(stmt).scalars().all()))
        return [e for e in results if e.enabled]

    def update_next_run(self, event_id: str, next_run: datetime) -> None:
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            obj = session.get(EventRecord, event_id)
            if obj:
                obj.next_run = next_run
                obj.updated_at = now
                session.add(obj)
                session.commit()
