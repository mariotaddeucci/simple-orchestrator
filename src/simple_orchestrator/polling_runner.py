import asyncio
import logging

from .db.orchestrator import OrchestratorDB
from .settings import PollingSettings

logger = logging.getLogger(__name__)


class PollingRunner:
    """
    Runs scheduled pollings defined in orchestrator.toml under [[pollings]].

    On start: all pollings fire immediately, then loop every interval_minutes.
    Deduplication: skips enqueue if identical (agent_id + prompt) is already
    pending or running in the queue.
    """

    def __init__(self, db: OrchestratorDB, pollings: list[PollingSettings]) -> None:
        self._db = db
        self._pollings = pollings

    async def run_forever(self) -> None:
        if not self._pollings:
            return
        logger.info("PollingRunner: starting %d polling(s)", len(self._pollings))
        await asyncio.gather(*[self._polling_loop(p) for p in self._pollings])

    async def _polling_loop(self, p: PollingSettings) -> None:
        await self._fire(p)
        while True:
            await asyncio.sleep(p.interval_minutes * 60)
            await self._fire(p)

    async def _fire(self, p: PollingSettings) -> None:
        try:
            if await self._db.has_duplicate_pending(p.agent_id, p.prompt):
                logger.debug(
                    "polling [%s]: skipped — duplicate pending/running", p.agent_id
                )
                return
            await self._db.enqueue(p.agent_id, p.prompt)
            logger.info(
                "polling [%s]: enqueued — %.60s%s",
                p.agent_id,
                p.prompt,
                "…" if len(p.prompt) > 60 else "",
            )
        except Exception:
            logger.exception("polling [%s]: error during enqueue", p.agent_id)
