from datetime import datetime
from pathlib import Path
from typing import Self

from sqlalchemy import Engine, select
from sqlmodel import Session

from simple_orchestrator.db.engine import build_engine
from simple_orchestrator.models.session import SessionRecord


def _clone[T](obj: T) -> T:
    """Return a detached Pydantic copy safe to use after the session closes."""
    return type(obj).model_validate(obj.model_dump())  # type: ignore[attr-defined]


def _clone_list[T](objs: list[T]) -> list[T]:
    return [_clone(o) for o in objs]


class SessionHistoryDB:
    def __init__(self, db_path: str | Path = "sessions.db") -> None:
        self._engine: Engine = build_engine(db_path)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        """No-op: engine is created in __init__. Kept for API compatibility."""

    def close(self) -> None:
        self._engine.dispose()

    def save(self, record: SessionRecord) -> None:
        with Session(self._engine) as session:
            session.merge(record)
            session.commit()

    def update_status(
        self,
        session_id: str,
        status: str,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None:
        with Session(self._engine) as session:
            record = session.get(SessionRecord, session_id)
            if record:
                record.status = status
                if ended_at is not None:
                    record.ended_at = ended_at
                if vendor_session_id is not None:
                    record.vendor_session_id = vendor_session_id
                session.add(record)
                session.commit()

    def get(self, session_id: str) -> SessionRecord | None:
        with Session(self._engine) as session:
            obj = session.get(SessionRecord, session_id)
            return _clone(obj) if obj else None

    def list_sessions(
        self,
        vendor: str | None = None,
        status: str | None = None,
    ) -> list[SessionRecord]:
        with Session(self._engine) as session:
            stmt = select(SessionRecord)
            if vendor is not None:
                stmt = stmt.where(SessionRecord.vendor == vendor)  # type: ignore[arg-type]
            if status is not None:
                stmt = stmt.where(SessionRecord.status == status)  # type: ignore[arg-type]
            stmt = stmt.order_by(SessionRecord.started_at.desc())  # type: ignore[arg-type]
            return _clone_list(list(session.execute(stmt).scalars().all()))
