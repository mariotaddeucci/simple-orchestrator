"""Mock agent vendor for TUI integration tests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from simple_orchestrator_core.models.model import ModelInfo
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_worker.vendors.base import BaseVendor

logger = logging.getLogger(__name__)


class MockAgent(BaseVendor):
    def __init__(
        self,
        session_store,
        *,
        should_fail: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        super().__init__(session_store)
        self._should_fail = should_fail
        self._delay_seconds = delay_seconds
        self.executed_sessions: list[tuple[str, str]] = []  # (session_id, prompt)

    @property
    def vendor_name(self) -> str:
        return "mock"

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        self.executed_sessions.append((session_id, config.prompt))
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
        if self._should_fail:
            raise RuntimeError("MockAgent configured to fail")

    async def _vendor_kill(self, session_id: str) -> None:
        logger.info("MockAgent killed: %s", session_id)

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        async def _gen() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "start", "prompt": config.prompt}
            if self._delay_seconds > 0:
                await asyncio.sleep(self._delay_seconds)
            if self._should_fail:
                yield {"type": "error", "message": "MockAgent configured to fail"}
            else:
                yield {"type": "complete", "result": f"Mock result for: {config.prompt[:30]}"}

        return _gen()

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id="mock-model-1", name="Mock Model 1", vendor="mock"),
        ]
