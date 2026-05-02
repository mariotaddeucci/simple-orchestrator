from collections.abc import AsyncIterator
from typing import Any

from copilot.client import CopilotClient
from copilot.session import CopilotSession

from ..db.history import SessionHistoryDB
from ..models.model import ModelInfo
from ..models.session import SessionConfig
from .base import BaseVendor


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
                    model=config.model or self._model,
                    workspace_path=config.workdir,
                )
                async with session:
                    yield {"type": "session_created", "session_id": session.session_id}
                    events: list[Any] = []
                    session.on(events.append)
                    await session.send(config.prompt)
                    for event in events:
                        yield {"type": "event", "data": event}

        return _stream()

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        async with CopilotClient() as client:
            copilot_session: CopilotSession = await client.create_session(
                model=config.model or self._model,
                workspace_path=config.workdir,
            )
            async with copilot_session:
                await self._db.update_status(
                    session_id,
                    "running",
                    vendor_session_id=copilot_session.session_id,
                )
                self._active_handles[session_id] = copilot_session

                done = False

                def _on_done(_: Any) -> None:
                    nonlocal done
                    done = True

                copilot_session.on(_on_done)
                await copilot_session.send(config.prompt)
                self._active_handles.pop(session_id, None)

    async def _vendor_kill(self, session_id: str) -> None:
        session: CopilotSession | None = self._active_handles.pop(session_id, None)
        if not session:
            return
        try:
            await session.abort()
        except Exception:
            pass
