import asyncio
import contextlib
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.session import SessionConfig, SessionRecord


class BaseVendor(ABC):
    def __init__(self, db: SessionHistoryDB) -> None:
        self._db = db
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._active_handles: dict[str, Any] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._on_done_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    @abstractmethod
    def vendor_name(self) -> str: ...

    async def run(self, config: SessionConfig) -> str:
        session_id = str(ULID())
        workdir = config.workdir if config.workdir is not None else tempfile.mkdtemp()
        if workdir != config.workdir:
            config = config.model_copy(update={"workdir": workdir})
        record = SessionRecord(
            id=session_id,
            vendor=self.vendor_name,
            prompt=config.prompt,
            workdir=workdir,
            started_at=datetime.now(UTC),
            status="running",
        )
        await self._db.save(record)

        task = asyncio.create_task(
            self._run_session(session_id, config),
            name=f"{self.vendor_name}-{session_id}",
        )
        self._active_tasks[session_id] = task
        self._attach_on_done(session_id, task)
        return session_id

    async def kill(self, session_id: str) -> None:
        task = self._active_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._vendor_kill(session_id)
        await self._db.update_status(session_id, "killed", datetime.now(UTC))

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return available models for this vendor."""
        ...

    @abstractmethod
    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        """Stream vendor events for a session without persisting to DB."""
        ...

    @abstractmethod
    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        """Background task: runs execute_session and drains it."""
        ...

    @abstractmethod
    async def _vendor_kill(self, session_id: str) -> None:
        """Vendor-specific abort/cleanup before DB status update."""
        ...

    async def resume(self, session_id: str, config: SessionConfig) -> str:
        """Resume an interrupted session reusing the same session_id.

        For vendors that pass session_id to their SDK (e.g. ClaudeCode), this
        enables native session resume via the SDK's session_id parameter.
        Other vendors fall back to re-running the session from scratch.

        Returns the session_id being resumed.
        """
        await self._db.update_status(session_id, "running")

        task = asyncio.create_task(
            self._run_session(session_id, config),
            name=f"{self.vendor_name}-resume-{session_id}",
        )
        self._active_tasks[session_id] = task
        self._attach_on_done(session_id, task)
        return session_id

    async def wait(self, session_id: str) -> SessionRecord | None:
        """Block until a running session completes. Safe to call after run() or resume()."""
        task = self._active_tasks.get(session_id)
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # Await the _on_done background task so the DB status is up-to-date before
        # we read the session record.
        on_done = self._on_done_tasks.pop(session_id, None)
        if on_done:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await on_done
        return await self._db.get(session_id)

    def _attach_on_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        """Register a done callback that tracks the _on_done background task."""

        def _on_done_callback(t: asyncio.Task[None]) -> None:
            bg = asyncio.create_task(self._on_done(session_id, t))
            self._background_tasks.add(bg)
            bg.add_done_callback(self._background_tasks.discard)
            self._on_done_tasks[session_id] = bg

        task.add_done_callback(_on_done_callback)

    async def _on_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        self._active_tasks.pop(session_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        status = "failed" if exc else "completed"
        await self._db.update_status(session_id, status, datetime.now(UTC))
