import contextlib
import json
import re
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.models.memory_record import MemoryRecord
from simple_orchestrator.models.queue_item import QueueItem


def _new_ulid() -> str:
    return str(ULID())


def _resolve_workdir(workdir: str | None) -> str:
    """Return an effective working directory for a queue item.

    - If *workdir* is None, a fresh temporary directory is created.
    - If *workdir* exists and is inside a git repository, the git root is
      returned instead so the agent always starts at the repo root.
    - Otherwise *workdir* is returned unchanged.
    """
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


class OrchestratorDB(SessionHistoryDB):
    async def _init_schema(self) -> None:
        await super()._init_schema()
        assert self._conn
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS queue (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                workdir TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                session_id TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                depends_on TEXT,
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS memory (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                description TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memory_agent_id ON memory (agent_id);

            CREATE TABLE IF NOT EXISTS cron_state (
                key TEXT PRIMARY KEY,
                last_run TEXT NOT NULL
            );
        """)
        await self._conn.commit()
        # Migrations: add columns that may be missing from older DBs.
        await self._add_column_if_missing("queue", "workdir", "TEXT")
        await self._add_column_if_missing("queue", "depends_on", "TEXT")
        await self._add_column_if_missing("queue", "note", "TEXT")

    async def _add_column_if_missing(self, table: str, column: str, col_type: str) -> None:
        assert self._conn
        _ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        _valid_types = {"TEXT", "INTEGER", "REAL", "BLOB", "NULL"}
        if not (_ident.match(table) and _ident.match(column) and col_type.upper() in _valid_types):
            msg = f"Invalid SQL identifier in migration: table={table!r}, column={column!r}, col_type={col_type!r}"
            raise ValueError(msg)
        try:
            await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            await self._conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    # ── queue ─────────────────────────────────────────────────────────────────

    async def enqueue(
        self,
        agent_id: str,
        prompt: str,
        workdir: str | None = None,
        depends_on: list[str] | None = None,
        item_id: str | None = None,
    ) -> QueueItem:
        assert self._conn
        item = QueueItem(
            id=item_id or _new_ulid(),
            agent_id=agent_id,
            prompt=prompt,
            workdir=_resolve_workdir(workdir),
            status="pending",
            created_at=datetime.now(UTC),
            depends_on=depends_on or [],
        )
        await self._conn.execute(
            "INSERT INTO queue (id, agent_id, prompt, workdir, status, created_at, depends_on) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.agent_id,
                item.prompt,
                item.workdir,
                item.status,
                item.created_at.isoformat(),
                json.dumps(item.depends_on) if item.depends_on else None,
            ),
        )
        await self._conn.commit()
        return item

    async def dequeue_next(self) -> QueueItem | None:
        """Claim the next pending item whose dependencies are all completed (FIFO by ULID).

        Items with unmet dependencies are skipped.
        Items whose dependencies have failed, been cancelled, or killed are automatically failed.
        """
        assert self._conn
        async with self._conn.execute(
            "SELECT id, agent_id, prompt, workdir, status, session_id, "
            "created_at, started_at, ended_at, depends_on, note "
            "FROM queue WHERE status = 'pending' ORDER BY id ASC",
        ) as cursor:
            rows = await cursor.fetchall()

        now = datetime.now(UTC).isoformat()
        for row in rows:
            item = _row_to_queue(row)
            if not item.depends_on:
                # No dependencies — claim immediately.
                await self._conn.execute(
                    "UPDATE queue SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
                    (now, item.id),
                )
                await self._conn.commit()
                return item

            # Fetch statuses of all dependency tasks.
            placeholders = ",".join("?" * len(item.depends_on))
            async with self._conn.execute(
                "SELECT id, status FROM queue WHERE id IN (" + placeholders + ")",  # noqa: S608
                item.depends_on,
            ) as dep_cursor:
                dep_rows = await dep_cursor.fetchall()

            dep_statuses = {r[0]: r[1] for r in dep_rows}

            # Any dependency that failed / was cancelled / was killed causes this item to fail too.
            terminal_failed = {did for did, st in dep_statuses.items() if st in ("failed", "cancelled", "killed")}
            # A dependency that doesn't exist at all is also treated as failed.
            missing = set(item.depends_on) - set(dep_statuses)
            if terminal_failed or missing:
                await self._conn.execute(
                    "UPDATE queue SET status = 'failed', ended_at = ? WHERE id = ?",
                    (now, item.id),
                )
                await self._conn.commit()
                continue

            # All dependencies must be 'completed' before we can start.
            if all(dep_statuses.get(did) == "completed" for did in item.depends_on):
                await self._conn.execute(
                    "UPDATE queue SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
                    (now, item.id),
                )
                await self._conn.commit()
                return item

            # Some dependencies are still pending or running — skip for now.

        return None

    async def update_queue_item(
        self,
        item_id: str,
        *,
        status: str,
        session_id: str | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        assert self._conn
        await self._conn.execute(
            "UPDATE queue SET status = ?, "
            "session_id = COALESCE(?, session_id), "
            "ended_at = COALESCE(?, ended_at) "
            "WHERE id = ?",
            (
                status,
                session_id,
                ended_at.isoformat() if ended_at else None,
                item_id,
            ),
        )
        await self._conn.commit()

    async def cancel_queue_item(self, item_id: str) -> None:
        assert self._conn
        await self._conn.execute(
            "UPDATE queue SET status = 'cancelled', ended_at = ? WHERE id = ? AND status = 'pending'",
            (datetime.now(UTC).isoformat(), item_id),
        )
        await self._conn.commit()

    async def add_task_note(self, item_id: str, note: str) -> bool:
        """Attach a summary note to a queue item. Returns True if the item exists."""
        assert self._conn
        cursor = await self._conn.execute("UPDATE queue SET note = ? WHERE id = ?", (note, item_id))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_queue_item(self, item_id: str) -> QueueItem | None:
        assert self._conn
        async with self._conn.execute(
            "SELECT id, agent_id, prompt, workdir, status, session_id, "
            "created_at, started_at, ended_at, depends_on, note FROM queue WHERE id = ?",
            (item_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_queue(row) if row else None

    async def has_duplicate_pending(self, agent_id: str, prompt: str) -> bool:
        """Return True if an identical (agent_id + prompt) item is pending or running."""
        assert self._conn
        async with self._conn.execute(
            "SELECT 1 FROM queue WHERE agent_id = ? AND prompt = ? AND status IN ('pending', 'running') LIMIT 1",
            (agent_id, prompt),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def list_queue(
        self,
        status: str | None = None,
        agent_id: str | None = None,
    ) -> list[QueueItem]:
        assert self._conn
        _cols = (
            "SELECT id, agent_id, prompt, workdir, status, session_id, "
            "created_at, started_at, ended_at, depends_on, note FROM queue"
        )
        if status is not None and agent_id is not None:
            query = _cols + " WHERE status = ? AND agent_id = ? ORDER BY id ASC"
            params: list[str] = [status, agent_id]
        elif status is not None:
            query = _cols + " WHERE status = ? ORDER BY id ASC"
            params = [status]
        elif agent_id is not None:
            query = _cols + " WHERE agent_id = ? ORDER BY id ASC"
            params = [agent_id]
        else:
            query = _cols + " ORDER BY id ASC"
            params = []
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_queue(r) for r in rows]

    # ── cron state ───────────────────────────────────────────────────────────

    async def get_cron_last_run(self, key: str) -> datetime | None:
        assert self._conn
        async with self._conn.execute("SELECT last_run FROM cron_state WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    async def set_cron_last_run(self, key: str, last_run: datetime) -> None:
        assert self._conn
        await self._conn.execute(
            "INSERT INTO cron_state (key, last_run) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET last_run = excluded.last_run",
            (key, last_run.isoformat()),
        )
        await self._conn.commit()

    # ── memory ────────────────────────────────────────────────────────────────

    async def save_memory(self, agent_id: str, description: str, content: str) -> MemoryRecord:
        assert self._conn
        now = datetime.now(UTC)
        memory_id = _new_ulid()
        await self._conn.execute(
            "INSERT INTO memory (id, agent_id, description, content, updated_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, agent_id, description, content, now.isoformat()),
        )
        await self._conn.commit()
        return MemoryRecord(id=memory_id, agent_id=agent_id, description=description, content=content, updated_at=now)

    async def get_memory(self, memory_id: str) -> MemoryRecord | None:
        assert self._conn
        async with self._conn.execute(
            "SELECT id, agent_id, description, content, updated_at FROM memory WHERE id = ?",
            (memory_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_memory(row) if row else None

    async def delete_memory(self, memory_id: str) -> bool:
        assert self._conn
        async with self._conn.execute("SELECT 1 FROM memory WHERE id = ?", (memory_id,)) as cursor:
            exists = await cursor.fetchone() is not None
        if exists:
            await self._conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
            await self._conn.commit()
        return exists

    async def list_memories(self, agent_id: str | None = None) -> list[MemoryRecord]:
        assert self._conn
        query = "SELECT id, agent_id, description, content, updated_at FROM memory"
        params: list[str] = []
        if agent_id:
            query += " WHERE agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY updated_at DESC"
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_memory(r) for r in rows]


def _row_to_queue(row: aiosqlite.Row) -> QueueItem:
    return QueueItem(
        id=row[0],
        agent_id=row[1],
        prompt=row[2],
        workdir=row[3],
        status=row[4],
        session_id=row[5],
        created_at=datetime.fromisoformat(row[6]),
        started_at=datetime.fromisoformat(row[7]) if row[7] else None,
        ended_at=datetime.fromisoformat(row[8]) if row[8] else None,
        depends_on=json.loads(row[9]) if row[9] else [],
        note=row[10],
    )


def _row_to_memory(row: aiosqlite.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row[0],
        agent_id=row[1],
        description=row[2],
        content=row[3],
        updated_at=datetime.fromisoformat(row[4]),
    )
