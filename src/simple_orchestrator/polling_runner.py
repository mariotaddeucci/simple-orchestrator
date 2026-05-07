import threading
import time

from .db.orchestrator import OrchestratorDB
from .logging_config import get_internal_logger
from .settings import PollingSettings

logger = get_internal_logger(__name__)


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
        self._running = False
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Start all polling loops. Blocks until stop() is called. Call from a thread worker."""
        if not self._pollings:
            return
        self._running = True
        logger.info("PollingRunner: starting %d polling(s)", len(self._pollings))
        for p in self._pollings:
            t = threading.Thread(target=self._polling_loop, args=(p,), daemon=True)
            self._threads.append(t)
            t.start()
        # Block until stop() is called
        while self._running:
            time.sleep(1)

    def stop(self) -> None:
        self._running = False

    def run_forever(self) -> None:
        """Alias for start() for backward compat."""
        self.start()

    def _polling_loop(self, p: PollingSettings) -> None:
        self._fire(p)
        while self._running:
            time.sleep(p.interval_minutes * 60)
            if self._running:
                self._fire(p)

    def _fire(self, p: PollingSettings) -> None:
        try:
            if self._db.has_duplicate_pending(p.agent_id, p.prompt):
                logger.debug("polling [%s]: skipped — duplicate pending/running", p.agent_id)
                return
            self._db.enqueue(p.agent_id, p.prompt)
            logger.info(
                "polling [%s]: enqueued — %.60s%s",
                p.agent_id,
                p.prompt,
                "..." if len(p.prompt) > 60 else "",
            )
        except Exception:
            logger.exception("polling [%s]: error during enqueue", p.agent_id)
