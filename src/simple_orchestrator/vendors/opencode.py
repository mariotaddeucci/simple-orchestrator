import contextlib
from typing import TYPE_CHECKING, Any

from opencode_ai import AsyncOpencode

from simple_orchestrator.logging_config import get_vendor_logger
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.vendors.base import BaseVendor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from simple_orchestrator.db.history import SessionHistoryDB
    from simple_orchestrator.models.session import SessionConfig

logger = get_vendor_logger(__name__)


class OpenCodeVendor(BaseVendor):
    def __init__(
        self,
        db: SessionHistoryDB,
        base_url: str | None = None,
        provider_id: str = "anthropic",
        model_id: str = "claude-sonnet-4-5",
    ) -> None:
        super().__init__(db)
        self._base_url = base_url
        self._provider_id = provider_id
        self._model_id = model_id
        self._active_handles: dict[str, tuple[AsyncOpencode, str]] = {}

    @property
    def vendor_name(self) -> str:
        return "opencode"

    async def list_models(self) -> list[ModelInfo]:
        async with AsyncOpencode(base_url=self._base_url) as client:
            cfg = await client.config.get()
        if not cfg.provider:
            return []
        models: list[ModelInfo] = []
        for provider_id, provider in cfg.provider.items():
            provider_name = provider.name or provider_id
            for model_id, model_meta in (provider.models or {}).items():
                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model_meta.name or model_id,
                        vendor="opencode",
                        provider=provider_name,
                    ),
                )
        return models

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        async def _stream() -> AsyncIterator[Any]:
            async with AsyncOpencode(base_url=self._base_url) as client:
                session = await client.session.create()
                yield {"type": "session_created", "session_id": session.id}
                model_id = config.model or self._model_id
                response = await client.session.chat(
                    session.id,
                    provider_id=self._provider_id,
                    model_id=model_id,
                    parts=[{"type": "text", "text": config.prompt}],
                )
                yield {"type": "response", "data": response}

        return _stream()

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        logger.info("OpenCode: starting session session_id=%s", session_id)
        logger.debug("OpenCode config: provider=%s model=%s", self._provider_id, config.model or self._model_id)
        async with AsyncOpencode(base_url=self._base_url) as client:
            vendor_session = await client.session.create()
            logger.debug("OpenCode vendor session created vendor_session_id=%s", vendor_session.id)
            self._db.update_status(session_id, "running", vendor_session_id=vendor_session.id)
            self._active_handles[session_id] = (client, vendor_session.id)

            model_id = config.model or self._model_id
            await client.session.chat(
                vendor_session.id,
                provider_id=self._provider_id,
                model_id=model_id,
                parts=[{"type": "text", "text": config.prompt}],
            )
            self._active_handles.pop(session_id, None)
            logger.info("OpenCode: session completed session_id=%s", session_id)

    async def _vendor_kill(self, session_id: str) -> None:
        handle = self._active_handles.pop(session_id, None)
        if not handle:
            return
        client, vendor_session_id = handle
        with contextlib.suppress(Exception):
            await client.session.abort(vendor_session_id)
