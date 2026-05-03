import sqlite3
from datetime import UTC, datetime

import aiosqlite
from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.models.agent_record import AgentRecord
from simple_orchestrator.models.memory_record import MemoryRecord
from simple_orchestrator.models.queue_item import QueueItem


def _new_ulid() -> str:
    return str(ULID())


class OrchestratorDB(SessionHistoryDB):
    async def _init_schema(self) -> None:
        await super()._init_schema()
        assert self._conn
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                nickname TEXT,
                prompt TEXT NOT NULL,
                model TEXT,
                vendor TEXT NOT NULL,
                workdir TEXT NOT NULL DEFAULT '.',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS queue (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                agent_nickname TEXT,
                prompt TEXT NOT NULL,
                workdir TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                session_id TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                FOREIGN KEY (agent_id) REFERENCES agents(id)
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
        # Migration: add workdir column to queue if it doesn't exist yet (existing DBs).
        try:
            await self._conn.execute("ALTER TABLE queue ADD COLUMN workdir TEXT")
            await self._conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    # ── agents ────────────────────────────────────────────────────────────────

    async def register_agent(
        self,
        name: str,
        prompt: str,
        vendor: str,
        workdir: str = ".",
        model: str | None = None,
        nickname: str | None = None,
    ) -> AgentRecord:
        assert self._conn
        record = AgentRecord(
            id=_new_ulid(),
            name=name,
            nickname=nickname,
            prompt=prompt,
            model=model,
            vendor=vendor,
            workdir=workdir,
            created_at=datetime.now(UTC),
        )
        await self._conn.execute(
            "INSERT INTO agents (id, name, nickname, prompt, model, vendor, workdir, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.name,
                record.nickname,
                record.prompt,
                record.model,
                record.vendor,
                record.workdir,
                record.created_at.isoformat(),
            ),
        )
        await self._conn.commit()
        return record

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        assert self._conn
        async with self._conn.execute(
            "SELECT id, name, nickname, prompt, model, vendor, workdir, created_at FROM agents WHERE id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_agent(row) if row else None

    async def list_agents(self, vendor: str | None = None) -> list[AgentRecord]:
        assert self._conn
        query = "SELECT id, name, nickname, prompt, model, vendor, workdir, created_at FROM agents"
        params: list[str] = []
        if vendor:
            query += " WHERE vendor = ?"
            params.append(vendor)
        query += " ORDER BY created_at DESC"
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_agent(r) for r in rows]

    async def delete_agent(self, agent_id: str) -> None:
        assert self._conn
        await self._conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await self._conn.commit()

    # ── queue ─────────────────────────────────────────────────────────────────

    async def enqueue(self, agent_id: str, prompt: str, workdir: str | None = None) -> QueueItem:
        assert self._conn
        agent = await self.get_agent(agent_id)
        item = QueueItem(
            id=_new_ulid(),
            agent_id=agent_id,
            agent_nickname=agent.nickname if agent else None,
            prompt=prompt,
            workdir=workdir,
            status="pending",
            created_at=datetime.now(UTC),
        )
        await self._conn.execute(
            "INSERT INTO queue (id, agent_id, agent_nickname, prompt, workdir, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.agent_id,
                item.agent_nickname,
                item.prompt,
                item.workdir,
                item.status,
                item.created_at.isoformat(),
            ),
        )
        await self._conn.commit()
        return item

    async def dequeue_next(self) -> QueueItem | None:
        """Atomically claim the next pending item (FIFO by ULID)."""
        assert self._conn
        async with self._conn.execute(
            "SELECT id, agent_id, agent_nickname, prompt, workdir, status, session_id, "
            "created_at, started_at, ended_at "
            "FROM queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        item = _row_to_queue(row)
        await self._conn.execute(
            "UPDATE queue SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
            (datetime.now(UTC).isoformat(), item.id),
        )
        await self._conn.commit()
        return item

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

    async def get_queue_item(self, item_id: str) -> QueueItem | None:
        assert self._conn
        async with self._conn.execute(
            "SELECT id, agent_id, agent_nickname, prompt, workdir, status, session_id, "
            "created_at, started_at, ended_at FROM queue WHERE id = ?",
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
            "SELECT id, agent_id, agent_nickname, prompt, workdir, status, session_id, "
            "created_at, started_at, ended_at FROM queue"
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


def _row_to_agent(row: aiosqlite.Row) -> AgentRecord:
    return AgentRecord(
        id=row[0],
        name=row[1],
        nickname=row[2],
        prompt=row[3],
        model=row[4],
        vendor=row[5],
        workdir=row[6],
        created_at=datetime.fromisoformat(row[7]),
    )


def _row_to_queue(row: aiosqlite.Row) -> QueueItem:
    return QueueItem(
        id=row[0],
        agent_id=row[1],
        agent_nickname=row[2],
        prompt=row[3],
        workdir=row[4],
        status=row[5],
        session_id=row[6],
        created_at=datetime.fromisoformat(row[7]),
        started_at=datetime.fromisoformat(row[8]) if row[8] else None,
        ended_at=datetime.fromisoformat(row[9]) if row[9] else None,
    )


def _row_to_memory(row: aiosqlite.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row[0],
        agent_id=row[1],
        description=row[2],
        content=row[3],
        updated_at=datetime.fromisoformat(row[4]),
    )
