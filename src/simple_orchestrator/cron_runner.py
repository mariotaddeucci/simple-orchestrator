import hashlib
import time
from datetime import UTC, datetime

from croniter import croniter

from .db.orchestrator import OrchestratorDB
from .logging_config import get_internal_logger
from .settings import CronSettings, OrchestratorSettings

logger = get_internal_logger(__name__)


def _cron_key(c: CronSettings) -> str:
    raw = f"{c.agent_id}|{c.cron}|{c.prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


class CronRunner:
    """
    Enqueues agent prompts on cron schedules.

    Behaviour:
      - If a cron entry has never run, enqueues immediately.
      - Otherwise, computes next_run from last_run via the cron expression and
        enqueues once that time has passed.
      - Skips enqueue if an identical (agent_id + prompt) item is already
        pending or running (same duplicate guard as the polling runner).
      - last_run is updated only when a new item is actually enqueued.
    """

    def __init__(
        self,
        db: OrchestratorDB,
        settings: OrchestratorSettings | None = None,
        check_interval: float = 15.0,
    ) -> None:
        self._db = db
        self._settings = settings or OrchestratorSettings()
        self._check_interval = check_interval
        self._running = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start cron loop. Blocks until stop() is called. Call from a thread worker."""
        self._running = True
        while self._running:
            self._tick()
            time.sleep(self._check_interval)

    def stop(self) -> None:
        self._running = False

    def run_forever(self) -> None:
        """Alias for start() for backward compat."""
        self.start()

    # ── internal loop ─────────────────────────────────────────────────────────

    def _tick(self) -> None:
        now = datetime.now(UTC)
        for cron_cfg in self._settings.crons:
            self._check_cron(cron_cfg, now)

    def _check_cron(self, cron_cfg: CronSettings, now: datetime) -> None:
        key = _cron_key(cron_cfg)
        last_run = self._db.get_cron_last_run(key)

        if last_run is None:
            should_run = True
        else:
            ci = croniter(cron_cfg.cron, last_run.replace(tzinfo=None))
            next_run = ci.get_next(datetime).replace(tzinfo=UTC)
            should_run = now >= next_run

        if not should_run:
            return

        duplicate = self._db.has_duplicate_pending(cron_cfg.agent_id, cron_cfg.prompt)
        if duplicate:
            logger.debug(
                "cron [%s] agent=%s: skip — duplicate pending/running",
                cron_cfg.cron,
                cron_cfg.agent_id,
            )
            return

        self._db.enqueue(cron_cfg.agent_id, cron_cfg.prompt)
        self._db.set_cron_last_run(key, now)
        logger.info("cron [%s] agent=%s: enqueued", cron_cfg.cron, cron_cfg.agent_id)
