import contextlib
import json
import re
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.logging_config import get_internal_logger
from simple_orchestrator.models.memory_record import MemoryRecord
from simple_orchestrator.models.queue_item import QueueItem

logger = get_internal_logger(__name__)


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
    def _init_schema(self) -> None:
        super()._init_schema()
        assert self._conn
        with self._lock:
            self._conn.executescript("""
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
            self._conn.commit()
        # Migrations: add columns that may be missing from older DBs.
        self._add_column_if_missing("queue", "workdir", "TEXT")
        self._add_column_if_missing("queue", "depends_on", "TEXT")
        self._add_column_if_missing("queue", "note", "TEXT")

    def _add_column_if_missing(self, table: str, column: str, col_type: str) -> None:
        assert self._conn
        _ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        _valid_types = {"TEXT", "INTEGER", "REAL", "BLOB", "NULL"}
        if not (_ident.match(table) and _ident.match(column) and col_type.upper() in _valid_types):
            msg = f"Invalid SQL identifier in migration: table={table!r}, column={column!r}, col_type={col_type!r}"
            raise ValueError(msg)
        try:
            with self._lock:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                self._conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    # ── queue ─────────────────────────────────────────────────────────────────

    def enqueue(
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
        logger.info("DB enqueue: creating item id=%s agent_id=%s workdir=%s", item.id, agent_id, item.workdir)
        with self._lock:
            self._conn.execute(
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
            self._conn.commit()
        logger.info("DB enqueue: committed item id=%s status=%s", item.id, item.status)
        return item

    def dequeue_next(self) -> QueueItem | None:
        """Claim the next pending item whose dependencies are all completed (FIFO by ULID).

        Items with unmet dependencies are skipped.
        Items whose dependencies have failed, been cancelled, or killed are automatically failed.
        """
        assert self._conn
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, agent_id, prompt, workdir, status, session_id, "
                "created_at, started_at, ended_at, depends_on, note "
                "FROM queue WHERE status = 'pending' ORDER BY id ASC",
            ).fetchall()

        rows_list = list(rows)
        logger.debug("DB dequeue_next: found %d pending items", len(rows_list))
        now = datetime.now(UTC).isoformat()
        for row in rows_list:
            item = _row_to_queue(row)
            if not item.depends_on:
                # No dependencies — claim immediately.
                logger.info("DB dequeue_next: claiming item id=%s agent_id=%s", item.id, item.agent_id)
                with self._lock:
                    cursor = self._conn.execute(
                        "UPDATE queue SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
                        (now, item.id),
                    )
                    self._conn.commit()
                    if cursor.rowcount == 0:
                        # Another thread/process claimed it — skip.
                        logger.debug("DB dequeue_next: item id=%s was already claimed by another process", item.id)
                        continue
                logger.info("DB dequeue_next: claimed item id=%s, now running", item.id)
                item.status = "running"
                item.started_at = datetime.fromisoformat(now)
                return item

            # Fetch statuses of all dependency tasks.
            placeholders = ",".join("?" * len(item.depends_on))
            with self._lock:
                dep_rows = self._conn.execute(
                    "SELECT id, status FROM queue WHERE id IN (" + placeholders + ")",  # noqa: S608
                    item.depends_on,
                ).fetchall()

            dep_statuses = {r[0]: r[1] for r in dep_rows}

            # Any dependency that failed / was cancelled / was killed causes this item to fail too.
            terminal_failed = {did for did, st in dep_statuses.items() if st in ("failed", "cancelled", "killed")}
            # A dependency that doesn't exist at all is also treated as failed.
            missing = set(item.depends_on) - set(dep_statuses)
            if terminal_failed or missing:
                with self._lock:
                    self._conn.execute(
                        "UPDATE queue SET status = 'failed', ended_at = ? WHERE id = ?",
                        (now, item.id),
                    )
                    self._conn.commit()
                continue

            # All dependencies must be 'completed' before we can start.
            if all(dep_statuses.get(did) == "completed" for did in item.depends_on):
                with self._lock:
                    cursor = self._conn.execute(
                        "UPDATE queue SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
                        (now, item.id),
                    )
                    self._conn.commit()
                    if cursor.rowcount == 0:
                        # Another thread/process claimed it — skip.
                        logger.debug("DB dequeue_next: item id=%s was already claimed by another process", item.id)
                        continue
                item.status = "running"
                item.started_at = datetime.fromisoformat(now)
                return item

            # Some dependencies are still pending or running — skip for now.

        return None

    def update_queue_item(
        self,
        item_id: str,
        *,
        status: str,
        session_id: str | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        assert self._conn
        with self._lock:
            self._conn.execute(
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
            self._conn.commit()

    def cancel_queue_item(self, item_id: str) -> None:
        assert self._conn
        with self._lock:
            self._conn.execute(
                "UPDATE queue SET status = 'cancelled', ended_at = ? WHERE id = ? AND status = 'pending'",
                (datetime.now(UTC).isoformat(), item_id),
            )
            self._conn.commit()

    def add_task_note(self, item_id: str, note: str) -> bool:
        """Attach a summary note to a queue item. Returns True if the item exists."""
        assert self._conn
        with self._lock:
            cursor = self._conn.execute("UPDATE queue SET note = ? WHERE id = ?", (note, item_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def get_queue_item(self, item_id: str) -> QueueItem | None:
        assert self._conn
        with self._lock:
            row = self._conn.execute(
                "SELECT id, agent_id, prompt, workdir, status, session_id, "
                "created_at, started_at, ended_at, depends_on, note FROM queue WHERE id = ?",
                (item_id,),
            ).fetchone()
        return _row_to_queue(row) if row else None

    def has_duplicate_pending(self, agent_id: str, prompt: str) -> bool:
        """Return True if an identical (agent_id + prompt) item is pending or running."""
        assert self._conn
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM queue WHERE agent_id = ? AND prompt = ? AND status IN ('pending', 'running') LIMIT 1",
                (agent_id, prompt),
            ).fetchone()
        return row is not None

    def list_queue(
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
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_queue(r) for r in rows]

    def cleanup_old_completed_items(
        self,
        max_items: int = 15,
        max_age_days: int = 7,
    ) -> int:
        """Remove completed items exceeding retention limits.

        Keeps at most *max_items* completed items (newest first) and removes
        completed items older than *max_age_days* days. Returns the number of
        deleted items.

        Only applies to items with status='completed'. Other statuses (pending,
        running, failed, cancelled, killed) are not affected.
        """
        assert self._conn
        now = datetime.now(UTC)
        cutoff_date = now - timedelta(days=max_age_days)

        # Get all completed items ordered by ended_at descending (newest first)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ended_at FROM queue WHERE status = 'completed' ORDER BY ended_at DESC",
            ).fetchall()

        # Convert to list for indexing
        completed_items = list(rows)
        to_delete: set[str] = set()

        # Mark items beyond max_items limit for deletion
        if len(completed_items) > max_items:
            for row in completed_items[max_items:]:
                to_delete.add(row[0])

        # Mark items older than max_age_days for deletion
        for row in completed_items:
            if row[1]:  # ended_at is not None
                ended_at = datetime.fromisoformat(row[1])
                if ended_at < cutoff_date:
                    to_delete.add(row[0])

        # Delete items in batch
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            with self._lock:
                self._conn.execute(
                    "DELETE FROM queue WHERE id IN (" + placeholders + ")",  # noqa: S608
                    list(to_delete),
                )
                self._conn.commit()
            logger.info("Cleaned up %d old completed queue items", len(to_delete))

        return len(to_delete)

    # ── cron state ───────────────────────────────────────────────────────────

    def get_cron_last_run(self, key: str) -> datetime | None:
        assert self._conn
        with self._lock:
            row = self._conn.execute("SELECT last_run FROM cron_state WHERE key = ?", (key,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def set_cron_last_run(self, key: str, last_run: datetime) -> None:
        assert self._conn
        with self._lock:
            self._conn.execute(
                "INSERT INTO cron_state (key, last_run) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET last_run = excluded.last_run",
                (key, last_run.isoformat()),
            )
            self._conn.commit()

    # ── memory ────────────────────────────────────────────────────────────────

    def save_memory(self, agent_id: str, description: str, content: str) -> MemoryRecord:
        assert self._conn
        now = datetime.now(UTC)
        memory_id = _new_ulid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO memory (id, agent_id, description, content, updated_at) VALUES (?, ?, ?, ?, ?)",
                (memory_id, agent_id, description, content, now.isoformat()),
            )
            self._conn.commit()
        return MemoryRecord(id=memory_id, agent_id=agent_id, description=description, content=content, updated_at=now)

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        assert self._conn
        with self._lock:
            row = self._conn.execute(
                "SELECT id, agent_id, description, content, updated_at FROM memory WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def delete_memory(self, memory_id: str) -> bool:
        assert self._conn
        with self._lock:
            exists = self._conn.execute("SELECT 1 FROM memory WHERE id = ?", (memory_id,)).fetchone() is not None
        if exists:
            with self._lock:
                self._conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
                self._conn.commit()
        return exists

    def list_memories(self, agent_id: str | None = None) -> list[MemoryRecord]:
        assert self._conn
        query = "SELECT id, agent_id, description, content, updated_at FROM memory"
        params: list[str] = []
        if agent_id:
            query += " WHERE agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_memory(r) for r in rows]


def _row_to_queue(row: sqlite3.Row) -> QueueItem:
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


def _row_to_memory(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row[0],
        agent_id=row[1],
        description=row[2],
        content=row[3],
        updated_at=datetime.fromisoformat(row[4]),
    )
