from datetime import UTC, datetime
from typing import TYPE_CHECKING

import anyio
from anyio import create_task_group

from .logging_config import get_internal_logger

if TYPE_CHECKING:
    from .db.orchestrator import OrchestratorDB
    from .settings import PollingSettings

logger = get_internal_logger(__name__)


def _polling_key(p: PollingSettings) -> str:
    """Generate a stable key for polling last_run persistence."""
    return f"polling_{p.agent_id}_{p.prompt}"


class PollingRunner:
    """
    Runs scheduled pollings defined in orchestrator.toml under [[pollings]].

    On start: all pollings fire immediately, then each loops at its interval.
    Deduplication: skips enqueue if identical (agent_id + prompt) is already
    pending or running in the queue.
    """

    def __init__(self, db: OrchestratorDB, pollings: list[PollingSettings]) -> None:
        self._db = db
        self._pollings = pollings
        self._running = False
        self._stop_event: anyio.Event | None = None

    async def start(self) -> None:
        """Start all polling loops. Blocks until stop() is called.
        Call from an async Textual worker — runs in the app's event loop.
        """
        if not self._pollings:
            return
        self._running = True
        self._stop_event = anyio.Event()
        logger.info("PollingRunner: starting %d polling(s)", len(self._pollings))

        for p in self._pollings:
            self._fire(p)

        try:
            async with create_task_group() as tg:
                for p in self._pollings:
                    tg.start_soon(self._polling_loop, p)
        finally:
            self._stop_event = None

    def stop(self) -> None:
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()

    async def _polling_loop(self, p: PollingSettings) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            with anyio.move_on_after(p.interval_minutes * 60):
                await self._stop_event.wait()
            if not self._stop_event.is_set():
                self._fire(p)

    def _fire(self, p: PollingSettings) -> None:
        try:
            if self._db.has_duplicate_pending(p.agent_id, p.prompt):
                logger.debug("polling [%s]: skipped — duplicate pending/running", p.agent_id)
                return
            self._db.enqueue(p.agent_id, p.prompt)
            # Persist last_run timestamp for schedule tracking
            self._db.set_cron_last_run(_polling_key(p), datetime.now(UTC))
            logger.info(
                "polling [%s]: enqueued — %.60s%s",
                p.agent_id,
                p.prompt,
                "…" if len(p.prompt) > 60 else "",
            )
        except Exception:
            logger.exception("polling [%s]: error during enqueue", p.agent_id)
