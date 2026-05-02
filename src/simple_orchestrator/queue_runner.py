import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from .db.orchestrator import OrchestratorDB
from .models.queue_item import QueueItem
from .models.session import SessionConfig
from .settings import AgentSettings, OrchestratorSettings
from .vendors.base import BaseVendor

logger = logging.getLogger(__name__)


@dataclass
class _AgentInfo:
    label: str
    vendor: str
    workdir: str
    prompt: str
    model: str | None
    mcp_servers: dict
    skills: list


class QueueRunner:
    """
    Processes queue items with bounded parallelism and per-workdir exclusion.

    Agent resolution order:
      1. settings.agents (TOML — versionable)
      2. DB agents table (programmatically registered)

    Concurrency rules:
      - At most `settings.max_active_sessions` items run simultaneously.
      - Items sharing the same workdir are serialised (per-dir asyncio.Lock).
      - Different workdirs run freely within the semaphore limit.
    """

    def __init__(
        self,
        db: OrchestratorDB,
        vendors: dict[str, BaseVendor],
        settings: OrchestratorSettings | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self._db = db
        self._vendors = vendors
        self._settings = settings or OrchestratorSettings()
        self._poll_interval = poll_interval

        self._semaphore = asyncio.Semaphore(self._settings.max_active_sessions)
        self._workdir_locks: dict[str, asyncio.Lock] = {}

        self._running = False
        self._loop_task: asyncio.Task[None] | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._loop(), name="queue-runner")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def run_forever(self) -> None:
        """Start the polling loop and block until cancelled."""
        self._running = True
        await self._loop()

    async def run_until_empty(self) -> None:
        """Block until there are no more pending items."""
        while True:
            await self._semaphore.acquire()
            item = await self._db.dequeue_next()
            if not item:
                self._semaphore.release()
                break
            asyncio.create_task(self._dispatch(item))

    # ── internal loop ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            await self._semaphore.acquire()
            item = await self._db.dequeue_next()
            if item:
                asyncio.create_task(self._dispatch(item))
            else:
                self._semaphore.release()
                await asyncio.sleep(self._poll_interval)

    async def _dispatch(self, item: QueueItem) -> None:
        info = await self._resolve_agent(item.agent_id)
        workdir = info.workdir if info else "."
        try:
            async with self._workdir_lock(workdir):
                await self._process(item, info)
        finally:
            self._semaphore.release()

    # ── execution ─────────────────────────────────────────────────────────────

    async def _process(self, item: QueueItem, info: _AgentInfo | None) -> None:
        if not info:
            logger.error("queue %s: agent '%s' not found in settings or DB", item.id, item.agent_id)
            await self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
            return

        vendor = self._vendors.get(info.vendor)
        if not vendor:
            logger.error("queue %s [%s]: vendor '%s' not registered", item.id, info.label, info.vendor)
            await self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
            return

        config = self._build_session_config(item, info)

        try:
            session_id = await vendor.run(config)
            await self._db.update_queue_item(item.id, status="running", session_id=session_id)

            record = await vendor.wait(session_id)
            final = record.status if record else "failed"
            queue_status = final if final in ("completed", "failed", "killed") else "failed"
        except Exception:
            logger.exception("queue %s [%s] raised an error", item.id, info.label)
            queue_status = "failed"

        await self._db.update_queue_item(item.id, status=queue_status, ended_at=datetime.now(UTC))
        logger.info("queue %s [%s] → %s", item.id, info.label, queue_status)

    def _build_session_config(self, item: QueueItem, info: _AgentInfo) -> SessionConfig:
        """Global MCPs/skills from settings merged with agent-specific ones."""
        merged_mcp = {**self._settings.mcp_servers, **info.mcp_servers}
        merged_skills = list(self._settings.skills) + list(info.skills)
        return SessionConfig(
            prompt=item.prompt,
            model=info.model,
            workdir=info.workdir,
            mcp_servers=merged_mcp,
            skills=merged_skills,
        )

    # ── agent resolution ──────────────────────────────────────────────────────

    async def _resolve_agent(self, agent_id: str) -> _AgentInfo | None:
        """Settings (TOML) take priority; DB agents are the fallback."""
        agent_s: AgentSettings | None = self._settings.agents.get(agent_id)
        if agent_s:
            return _AgentInfo(
                label=agent_s.label,
                vendor=agent_s.vendor,
                workdir=agent_s.workdir,
                prompt=agent_s.resolve_prompt(),
                model=agent_s.model,
                mcp_servers=dict(agent_s.mcp_servers),
                skills=list(agent_s.skills),
            )

        agent_r = await self._db.get_agent(agent_id)
        if agent_r:
            return _AgentInfo(
                label=agent_r.nickname or agent_r.name,
                vendor=agent_r.vendor,
                workdir=agent_r.workdir,
                prompt=agent_r.prompt,
                model=agent_r.model,
                mcp_servers={},
                skills=[],
            )

        return None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _workdir_lock(self, workdir: str) -> asyncio.Lock:
        if workdir not in self._workdir_locks:
            self._workdir_locks[workdir] = asyncio.Lock()
        return self._workdir_locks[workdir]

    @property
    def active_count(self) -> int:
        return self._settings.max_active_sessions - self._semaphore._value
