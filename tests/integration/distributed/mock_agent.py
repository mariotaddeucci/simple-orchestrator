"""Mock agent vendor for testing purposes."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from simple_orchestrator_core.models.model import ModelInfo
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_worker.vendors.base import BaseVendor

logger = logging.getLogger(__name__)


class MockAgent(BaseVendor):
    """
    Mock agent vendor that returns predictable values for testing.

    This agent simulates a real vendor but completes immediately with
    configurable behavior. Useful for testing UI/queue integration
    without requiring actual vendor setup.
    """

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
        logger.info("MockAgent initialized: should_fail=%s, delay=%s", should_fail, delay_seconds)

    @property
    def vendor_name(self) -> str:
        return "mock"

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        """Simulate a session run with logging of state transitions."""
        logger.info("MockAgent: session %s starting with prompt: %s", session_id, config.prompt[:50])
        self.executed_sessions.append((session_id, config.prompt))

        # Simulate work being done
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
        logger.info("MockAgent: session %s work completed", session_id)

        if self._should_fail:
            logger.error("MockAgent: session %s deliberately failing", session_id)
            raise RuntimeError("MockAgent configured to fail")

        logger.info("MockAgent: session %s completed successfully", session_id)

    async def _vendor_kill(self, session_id: str) -> None:
        """Kill the mock session."""
        logger.warning("MockAgent: session %s killed", session_id)

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        """Stream mock events for a session."""
        logger.info("MockAgent: execute_session called for prompt: %s", config.prompt[:50])

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
        """Return mock model info."""
        return [
            ModelInfo(id="mock-model-1", name="Mock Model 1", vendor="mock"),
            ModelInfo(id="mock-model-2", name="Mock Model 2", vendor="mock"),
        ]
