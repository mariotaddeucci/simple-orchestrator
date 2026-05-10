from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any

import httpx
from simple_orchestrator_core.models.model import ModelInfo

from simple_orchestrator_worker.logging_config import get_vendor_logger
from simple_orchestrator_worker.vendors.base import BaseVendor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from simple_orchestrator_core.models.session import SessionConfig

logger = get_vendor_logger(__name__)


class JulesVendor(BaseVendor):
    """Jules Code Agent Vendor - Cloud based, communicates via REST API."""

    def __init__(
        self,
        session_store,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "jules-v1",
    ) -> None:
        super().__init__(session_store)
        self._base_url = (base_url or os.getenv("JULES_API_URL") or "https://api.jules.ai/v1").rstrip("/")
        self._api_key = api_key or os.getenv("JULES_API_KEY")
        self._model = model
        self._active_sessions: dict[str, str] = {}  # session_id -> vendor_session_id

    @property
    def vendor_name(self) -> str:
        return "jules"

    def _client(self) -> httpx.AsyncClient:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=60.0)

    async def list_models(self) -> list[ModelInfo]:
        # Jules currently has one primary model, but could fetch from API in future
        return [
            ModelInfo(
                id=self._model,
                name="Jules Code Agent",
                vendor="jules",
            ),
        ]

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        async def _stream() -> AsyncIterator[Any]:
            async with self._client() as client:
                # 1. Create session
                r = await client.post("/sessions", json={"workdir": config.workdir})
                r.raise_for_status()
                vendor_session_id = r.json()["id"]
                yield {"type": "session_created", "session_id": vendor_session_id}

                # 2. Start chat/stream
                async with client.stream(
                    "POST",
                    f"/sessions/{vendor_session_id}/chat",
                    json={"prompt": config.prompt, "model": config.model or self._model},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            yield {"type": "chunk", "data": line}

        return _stream()

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        logger.info("Jules: starting session session_id=%s", session_id)
        async with self._client() as client:
            # Create vendor session
            r = await client.post("/sessions", json={"workdir": config.workdir})
            r.raise_for_status()
            vendor_session_id = r.json()["id"]

            logger.debug("Jules vendor session created vendor_session_id=%s", vendor_session_id)
            await self._store.update_status(session_id, "running", vendor_session_id=vendor_session_id)
            self._active_sessions[session_id] = vendor_session_id

            # Execute chat
            chat_r = await client.post(
                f"/sessions/{vendor_session_id}/chat",
                json={
                    "prompt": config.prompt,
                    "model": config.model or self._model,
                },
            )
            chat_r.raise_for_status()

            self._active_sessions.pop(session_id, None)
            logger.info("Jules: session completed session_id=%s", session_id)

    async def _vendor_kill(self, session_id: str) -> None:
        vendor_session_id = self._active_sessions.pop(session_id, None)
        if not vendor_session_id:
            return

        with contextlib.suppress(Exception):
            async with self._client() as client:
                await client.post(f"/sessions/{vendor_session_id}/abort")
