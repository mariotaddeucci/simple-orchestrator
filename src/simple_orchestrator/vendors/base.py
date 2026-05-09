import tempfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import anyio
from ulid import ULID

from simple_orchestrator.logging_config import get_vendor_logger
from simple_orchestrator.models.session import SessionConfig, SessionRecord

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from simple_orchestrator.db.history import SessionHistoryDB
    from simple_orchestrator.models.model import ModelInfo

logger = get_vendor_logger(__name__)


class BaseVendor(ABC):
    def __init__(self, db: SessionHistoryDB) -> None:
        self._db = db

    @property
    @abstractmethod
    def vendor_name(self) -> str: ...

    async def kill(self, session_id: str) -> None:
        """Best-effort kill for an in-flight vendor session."""
        with anyio.CancelScope(shield=True):
            await self._vendor_kill(session_id)
        self._db.update_status(session_id, "killed", datetime.now(UTC))

    async def run(self, config: SessionConfig, timeout_minutes: float = 30.0) -> tuple[str, str]:
        """Run a vendor session. Returns (session_id, final_status). Blocks until done.

        Compatible with both asyncio and trio backends via anyio.
        """
        session_id = str(ULID())
        workdir = config.workdir or tempfile.mkdtemp()
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
        self._db.save(record)
        logger.info("Starting vendor session session_id=%s vendor=%s workdir=%s", session_id, self.vendor_name, workdir)

        try:
            with anyio.fail_after(timeout_minutes * 60):
                await self._run_session(session_id, config)
            final_status = "completed"
        except anyio.get_cancelled_exc_class():
            logger.info("Session %s cancelled", session_id)
            with anyio.CancelScope(shield=True):
                await self._vendor_kill(session_id)
            final_status = "killed"
        except TimeoutError:
            logger.warning("Session %s timed out after %.1f min", session_id, timeout_minutes)
            with anyio.CancelScope(shield=True):
                await self._vendor_kill(session_id)
            final_status = "failed"
        except Exception:
            logger.exception("Session %s failed", session_id)
            final_status = "failed"

        self._db.update_status(session_id, final_status, datetime.now(UTC))
        logger.info("Session %s -> %s", session_id, final_status)
        return session_id, final_status

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]: ...

    @abstractmethod
    async def _run_session(self, session_id: str, config: SessionConfig) -> None: ...

    @abstractmethod
    async def _vendor_kill(self, session_id: str) -> None: ...
