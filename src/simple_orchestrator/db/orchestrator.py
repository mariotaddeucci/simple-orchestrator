import contextlib
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlmodel import Session
from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB, _clone, _clone_list
from simple_orchestrator.logging_config import get_internal_logger
from simple_orchestrator.models.cron_state import CronState
from simple_orchestrator.models.memory_record import MemoryRecord
from simple_orchestrator.models.queue_item import QueueItem

logger = get_internal_logger(__name__)


def _new_ulid() -> str:
    return str(ULID())


def _resolve_workdir(workdir: str | None) -> str:
    if workdir is None:
        return tempfile.mkdtemp()

    path = Path(workdir)
    if path.exists() and path.is_dir():
        with contextlib.suppress(subprocess.CalledProcessError):
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()

    return workdir


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class OrchestratorDB(SessionHistoryDB):
    # ── queue ─────────────────────────────────────────────────────────────────

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
            workdir=_resolve_workdir(workdir),
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

    def update_queue_item(
        self,
        item_id: str,
        *,
        status: str,
        session_id: str | None = None,
        ended_at: datetime | None = None,
        started_at: datetime | None = None,
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
                session.add(item)
                session.commit()

    def reset_to_pending(self, item_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(QueueItem)
                .where(QueueItem.id == item_id)  # type: ignore[arg-type]
                .values(status="pending", started_at=None, session_id=None, ended_at=None),
            )
            session.commit()

    def cancel_queue_item(self, item_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(QueueItem)
                .where(QueueItem.id == item_id, QueueItem.status == "pending")  # type: ignore[arg-type]
                .values(status="cancelled", ended_at=datetime.now(UTC)),
            )
            session.commit()

    def add_task_note(self, item_id: str, note: str) -> bool:
        with Session(self._engine) as session:
            result = session.execute(update(QueueItem).where(QueueItem.id == item_id).values(note=note))  # type: ignore[arg-type]
            session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def get_queue_item(self, item_id: str) -> QueueItem | None:
        with Session(self._engine) as session:
            obj = session.get(QueueItem, item_id)
            return _clone(obj) if obj else None

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

    def list_queue(
        self,
        status: str | None = None,
        agent_id: str | None = None,
    ) -> list[QueueItem]:
        with Session(self._engine) as session:
            stmt = select(QueueItem)
            if status is not None:
                stmt = stmt.where(QueueItem.status == status)  # type: ignore[arg-type]
            if agent_id is not None:
                stmt = stmt.where(QueueItem.agent_id == agent_id)  # type: ignore[arg-type]
            stmt = stmt.order_by(QueueItem.id)
            return _clone_list(list(session.execute(stmt).scalars().all()))

    def _ids_to_delete(self, completed: list[QueueItem], max_items: int, cutoff: datetime) -> set[str]:
        to_delete: set[str] = set()
        if len(completed) > max_items:
            for item in completed[max_items:]:
                to_delete.add(item.id)
        for item in completed:
            if item.ended_at and _as_utc(item.ended_at) < cutoff:
                to_delete.add(item.id)
        return to_delete

    def _delete_queue_items(self, ids: set[str]) -> None:
        with Session(self._engine) as session:
            for item_id in ids:
                obj = session.get(QueueItem, item_id)
                if obj:
                    session.delete(obj)
            session.commit()

    def cleanup_old_completed_items(self, max_items: int = 15, max_age_days: int = 7) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        with Session(self._engine) as session:
            completed = _clone_list(
                list(
                    session.execute(
                        select(QueueItem).where(QueueItem.status == "completed").order_by(QueueItem.ended_at.desc()),  # type: ignore[attr-defined]
                    )
                    .scalars()
                    .all(),
                ),
            )

        to_delete = self._ids_to_delete(completed, max_items, cutoff)
        if to_delete:
            self._delete_queue_items(to_delete)
            logger.info("Cleaned up %d old completed queue items", len(to_delete))

        return len(to_delete)

    # ── cron state ───────────────────────────────────────────────────────────

    def get_cron_last_run(self, key: str) -> datetime | None:
        with Session(self._engine) as session:
            row = session.get(CronState, key)
            return row.last_run if row else None

    def set_cron_last_run(self, key: str, last_run: datetime) -> None:
        with Session(self._engine) as session:
            existing = session.get(CronState, key)
            if existing:
                existing.last_run = last_run
                session.add(existing)
            else:
                session.add(CronState(key=key, last_run=last_run))
            session.commit()

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
