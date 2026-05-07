import contextlib
from collections.abc import AsyncIterator
from typing import Any

from copilot.client import CopilotClient
from copilot.generated.session_events import PermissionRequest
from copilot.session import CopilotSession, PermissionRequestResult

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.logging_config import get_vendor_logger
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.session import SessionConfig
from simple_orchestrator.vendors.base import BaseVendor

logger = get_vendor_logger(__name__)


def _auto_approve(_request: PermissionRequest, _env: dict[str, str]) -> PermissionRequestResult:
    return PermissionRequestResult(kind="approve-once")


class GithubCopilotVendor(BaseVendor):
    def __init__(
        self,
        db: SessionHistoryDB,
        model: str = "gpt-4o",
    ) -> None:
        super().__init__(db)
        self._model = model

    @property
    def vendor_name(self) -> str:
        return "github_copilot"

    async def list_models(self) -> list[ModelInfo]:
        async with CopilotClient() as client:
            raw_models = await client.list_models()
        return [
            ModelInfo(
                id=m.id,
                name=m.name,
                vendor="github_copilot",
            )
            for m in raw_models
        ]

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        async def _stream() -> AsyncIterator[Any]:
            async with CopilotClient() as client:
                session: CopilotSession = await client.create_session(
                    on_permission_request=_auto_approve,
                    model=config.model or self._model,
                    working_directory=config.workdir,
                )
                async with session:
                    yield {"type": "session_created", "session_id": session.session_id}
                    events: list[Any] = []
                    session.on(events.append)
                    await session.send_and_wait(config.prompt)
                    for event in events:
                        yield {"type": "event", "data": event}

        return _stream()

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        logger.info("GitHub Copilot: starting session session_id=%s", session_id)
        logger.debug("GitHub Copilot config: model=%s workdir=%s", config.model or self._model, config.workdir)
        async with CopilotClient() as client:
            copilot_session: CopilotSession = await client.create_session(
                on_permission_request=_auto_approve,
                model=config.model or self._model,
                working_directory=config.workdir,
            )
            async with copilot_session:
                logger.debug("GitHub Copilot vendor session created vendor_session_id=%s", copilot_session.session_id)
                await self._db.update_status(
                    session_id,
                    "running",
                    vendor_session_id=copilot_session.session_id,
                )
                self._active_handles[session_id] = copilot_session
                await copilot_session.send_and_wait(config.prompt)
                self._active_handles.pop(session_id, None)
                logger.info("GitHub Copilot: session completed session_id=%s", session_id)

    async def _vendor_kill(self, session_id: str) -> None:
        session: CopilotSession | None = self._active_handles.pop(session_id, None)
        if not session:
            return
        with contextlib.suppress(Exception):
            await session.abort()
