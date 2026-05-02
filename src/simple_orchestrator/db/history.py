from datetime import datetime
from typing import Self

import aiosqlite

from simple_orchestrator.models.session import SessionRecord


class SessionHistoryDB:
    def __init__(self, db_path: str = "sessions.db"):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._init_schema()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _init_schema(self) -> None:
        assert self._conn
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                vendor TEXT NOT NULL,
                prompt TEXT NOT NULL,
                workdir TEXT NOT NULL,
                started_at TEXT NOT NULL,
                status TEXT NOT NULL,
                ended_at TEXT,
                vendor_session_id TEXT
            )
        """)
        await self._conn.commit()

    async def save(self, record: SessionRecord) -> None:
        assert self._conn
        await self._conn.execute(
            """
            INSERT INTO sessions
                (id, vendor, prompt, workdir, started_at, status, ended_at, vendor_session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.vendor,
                record.prompt,
                record.workdir,
                record.started_at.isoformat(),
                record.status,
                record.ended_at.isoformat() if record.ended_at else None,
                record.vendor_session_id,
            ),
        )
        await self._conn.commit()

    async def update_status(
        self,
        session_id: str,
        status: str,
        ended_at: datetime | None = None,
        vendor_session_id: str | None = None,
    ) -> None:
        assert self._conn
        await self._conn.execute(
            """
            UPDATE sessions
            SET status = ?,
                ended_at = ?,
                vendor_session_id = COALESCE(?, vendor_session_id)
            WHERE id = ?
            """,
            (
                status,
                ended_at.isoformat() if ended_at else None,
                vendor_session_id,
                session_id,
            ),
        )
        await self._conn.commit()

    async def get(self, session_id: str) -> SessionRecord | None:
        assert self._conn
        async with self._conn.execute(
            "SELECT id, vendor, prompt, workdir, started_at, status, ended_at, vendor_session_id "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_record(row)

    async def list_sessions(
        self,
        vendor: str | None = None,
        status: str | None = None,
    ) -> list[SessionRecord]:
        assert self._conn
        conditions: list[str] = []
        params: list[str] = []
        if vendor is not None:
            conditions.append("vendor = ?")
            params.append(vendor)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = (
            "SELECT id, vendor, prompt, workdir, started_at, status, ended_at, vendor_session_id "
            "FROM sessions " + where + " ORDER BY started_at DESC"
        )
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_record(r) for r in rows]


def _row_to_record(row: aiosqlite.Row) -> SessionRecord:
    return SessionRecord(
        id=row[0],
        vendor=row[1],
        prompt=row[2],
        workdir=row[3],
        started_at=datetime.fromisoformat(row[4]),
        status=row[5],
        ended_at=datetime.fromisoformat(row[6]) if row[6] else None,
        vendor_session_id=row[7],
    )
