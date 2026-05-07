import asyncio
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.logging_config import get_vendor_logger
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.session import SessionConfig, SessionRecord

logger = get_vendor_logger(__name__)


class BaseVendor(ABC):
    def __init__(self, db: SessionHistoryDB) -> None:
        self._db = db

    @property
    @abstractmethod
    def vendor_name(self) -> str: ...

    def run_sync(
        self,
        config: SessionConfig,
        timeout_minutes: float = 30.0,
        existing_session_id: str | None = None,
    ) -> tuple[str, str]:
        """Run vendor session synchronously in current thread. Returns (session_id, final_status). Blocks until done."""
        session_id = existing_session_id or str(ULID())
        workdir = config.workdir or tempfile.mkdtemp()
        if workdir != config.workdir:
            config = config.model_copy(update={"workdir": workdir})

        if not existing_session_id:
            record = SessionRecord(
                id=session_id,
                vendor=self.vendor_name,
                prompt=config.prompt,
                workdir=workdir,
                started_at=datetime.now(UTC),
                status="running",
            )
            self._db.save(record)
        else:
            self._db.update_status(session_id, "running")

        logger.info("Starting vendor session session_id=%s vendor=%s", session_id, self.vendor_name)
        try:
            asyncio.run(
                asyncio.wait_for(
                    self._run_session(session_id, config),
                    timeout=timeout_minutes * 60,
                ),
            )
            final_status = "completed"
        except TimeoutError:
            logger.warning("Session %s timed out after %.1f min", session_id, timeout_minutes)
            final_status = "failed"
        except Exception:
            logger.exception("Session %s failed", session_id)
            final_status = "failed"

        self._db.update_status(session_id, final_status, datetime.now(UTC))
        logger.info("Session %s -> %s", session_id, final_status)
        return session_id, final_status

    def kill_sync(self, session_id: str) -> None:
        """Mark session as killed in DB. Best-effort: running thread may still complete."""
        asyncio.run(self._vendor_kill(session_id))
        self._db.update_status(session_id, "killed", datetime.now(UTC))

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]: ...

    @abstractmethod
    async def _run_session(self, session_id: str, config: SessionConfig) -> None: ...

    @abstractmethod
    async def _vendor_kill(self, session_id: str) -> None: ...
