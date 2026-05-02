import asyncio
import hashlib
import logging
from datetime import UTC, datetime

from croniter import croniter

from .db.orchestrator import OrchestratorDB
from .settings import CronSettings, OrchestratorSettings

logger = logging.getLogger(__name__)


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
        self._loop_task: asyncio.Task[None] | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._loop(), name="cron-runner")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def run_forever(self) -> None:
        """Start the cron loop and block until cancelled."""
        self._running = True
        await self._loop()

    # ── internal loop ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            await self._tick()
            await asyncio.sleep(self._check_interval)

    async def _tick(self) -> None:
        now = datetime.now(UTC)
        for cron_cfg in self._settings.crons:
            await self._check_cron(cron_cfg, now)

    async def _check_cron(self, cron_cfg: CronSettings, now: datetime) -> None:
        key = _cron_key(cron_cfg)
        last_run = await self._db.get_cron_last_run(key)

        if last_run is None:
            should_run = True
        else:
            ci = croniter(cron_cfg.cron, last_run.replace(tzinfo=None))
            next_run = ci.get_next(datetime).replace(tzinfo=UTC)
            should_run = now >= next_run

        if not should_run:
            return

        duplicate = await self._db.has_duplicate_pending(cron_cfg.agent_id, cron_cfg.prompt)
        if duplicate:
            logger.debug(
                "cron [%s] agent=%s: skip — duplicate pending/running",
                cron_cfg.cron,
                cron_cfg.agent_id,
            )
            return

        await self._db.enqueue(cron_cfg.agent_id, cron_cfg.prompt)
        await self._db.set_cron_last_run(key, now)
        logger.info("cron [%s] agent=%s: enqueued", cron_cfg.cron, cron_cfg.agent_id)
