import tempfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import anyio
from simple_orchestrator_core.models.session import SessionConfig, SessionRecord
from simple_orchestrator_core.settings import WorkerSettings
from ulid import ULID

from simple_orchestrator_worker.logging_config import get_vendor_logger
from simple_orchestrator_worker.session_store import SessionStore
from simple_orchestrator_worker.workdir import is_git_worktree, resolve_workdir

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from simple_orchestrator_core.models.model import ModelInfo

logger = get_vendor_logger(__name__)


class BaseVendor(ABC):
    def __init__(self, session_store: SessionStore, settings: WorkerSettings | None = None) -> None:
        self._store = session_store
        self._settings = settings or WorkerSettings()

    @property
    @abstractmethod
    def vendor_name(self) -> str: ...

    async def kill(self, session_id: str) -> None:
        """Best-effort kill for an in-flight vendor session."""
        with anyio.CancelScope(shield=True):
            await self._vendor_kill(session_id)
        await self._store.update_status(session_id, "killed", ended_at=datetime.now(UTC))

    async def _prepare_config(self, config: SessionConfig) -> SessionConfig:
        """Prepare the session configuration by resolving workdir and injecting instructions."""
        workdir = await anyio.to_thread.run_sync(
            lambda: resolve_workdir(config.workdir, self._settings.git_cache_dir),
        ) or tempfile.mkdtemp()

        new_values: dict[str, Any] = {"workdir": workdir}

        # Global setting for PR, but only if we have a workdir and it is a git worktree.
        is_git = await anyio.to_thread.run_sync(lambda: is_git_worktree(workdir))

        if self._settings.always_open_pr and is_git:
            pr_instruction = "Ao finalizar as modificações, abra um Pull Request com o que foi alterado."
            if pr_instruction not in config.prompt:
                new_values["prompt"] = f"{config.prompt}\n\n{pr_instruction}"

        return config.model_copy(update=new_values)

    async def run(
        self,
        config: SessionConfig,
        *,
        timeout_minutes: float = 30.0,
        session_id: str | None = None,
    ) -> tuple[str, str]:
        """Run a vendor session. Returns (session_id, final_status). Blocks until done.

        Compatible with both asyncio and trio backends via anyio.
        """
        session_id = session_id or str(ULID())
        config = await self._prepare_config(config)
        workdir = config.workdir

        record = SessionRecord(
            id=session_id,
            vendor=self.vendor_name,
            prompt=config.prompt,
            workdir=workdir,
            started_at=datetime.now(UTC),
            status="running",
        )
        await self._store.save(record)
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

        await self._store.update_status(session_id, final_status, ended_at=datetime.now(UTC))
        logger.info("Session %s -> %s", session_id, final_status)
        return session_id, final_status

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        """Execute a session and return an async iterator of events.

        Note: Implementations should NOT call _prepare_config themselves if called via worker,
        but external callers should use prepare_and_execute instead.
        """
        ...

    async def prepare_and_execute(self, config: SessionConfig) -> AsyncIterator[Any]:
        """Prepare config and then execute the session."""
        prepared_config = await self._prepare_config(config)
        async for chunk in await self.execute_session(prepared_config):
            yield chunk

    @abstractmethod
    async def _run_session(self, session_id: str, config: SessionConfig) -> None: ...

    @abstractmethod
    async def _vendor_kill(self, session_id: str) -> None: ...
