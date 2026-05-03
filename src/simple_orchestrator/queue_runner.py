import asyncio
import contextlib
import fnmatch
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .db.orchestrator import OrchestratorDB
from .models.queue_item import QueueItem
from .models.session import SessionConfig
from .models.skill import SkillConfig
from .settings import AgentSettings, OrchestratorSettings
from .vendors.base import BaseVendor

logger = logging.getLogger(__name__)


@dataclass
class _AgentInfo:
    label: str
    vendor: str
    workdir: str | None
    prompt: str
    model: str | None
    mcp_servers: dict
    skills: list
    timeout_minutes: float | None = None
    skill_globs: list[str] = field(default_factory=list)


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
        self._dispatch_tasks: set[asyncio.Task[None]] = set()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.resume_zombie_sessions()
        self._loop_task = asyncio.create_task(self._loop(), name="queue-runner")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task

    async def run_forever(self) -> None:
        """Start the polling loop and block until cancelled."""
        self._running = True
        await self.resume_zombie_sessions()
        await self._loop()

    async def run_until_empty(self) -> None:
        """Block until there are no more pending items."""
        await self.resume_zombie_sessions()
        while True:
            await self._semaphore.acquire()
            item = await self._db.dequeue_next()
            if item:
                task = asyncio.create_task(self._dispatch(item))
                self._dispatch_tasks.add(task)
                task.add_done_callback(self._dispatch_tasks.discard)
            else:
                self._semaphore.release()
                if self._dispatch_tasks:
                    # Running tasks may complete their dependencies; wait for at least one to
                    # finish before retrying dequeue so dependent items can be unlocked.
                    await asyncio.wait(self._dispatch_tasks, return_when=asyncio.FIRST_COMPLETED)
                else:
                    break

    # ── zombie resume ─────────────────────────────────────────────────────────

    async def resume_zombie_sessions(self) -> None:
        """Resume queue items left in 'running' state from a previous run.

        Called automatically on startup (start / run_forever / run_until_empty)
        so that sessions interrupted by an application restart are continued
        from where they stopped rather than left as permanent zombies.
        """
        zombie_items = await self._db.list_queue(status="running")
        if not zombie_items:
            return
        logger.info("QueueRunner: found %d zombie session(s), resuming…", len(zombie_items))
        for item in zombie_items:
            task = asyncio.create_task(self._resume_zombie(item), name=f"resume-{item.id}")
            self._dispatch_tasks.add(task)
            task.add_done_callback(self._dispatch_tasks.discard)

    async def _resume_zombie(self, item: QueueItem) -> None:
        """Acquire a semaphore slot and resume a single zombie queue item."""
        await self._semaphore.acquire()
        workdir = item.workdir or item.id
        try:
            async with self._workdir_lock(workdir):
                await self._resume_process(item)
        finally:
            self._semaphore.release()

    async def _resume_process(self, item: QueueItem) -> None:
        info = await self._resolve_agent(item.agent_id)
        if not info:
            logger.error("zombie %s: agent '%s' not found in settings or DB", item.id, item.agent_id)
            await self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
            return

        vendor = self._vendors.get(info.vendor)
        if not vendor:
            logger.error("zombie %s [%s]: vendor '%s' not registered", item.id, info.label, info.vendor)
            await self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
            return

        filtered_skills, tmp_skills_dir = self._filter_skills_to_tmpdir(info.skill_globs, item, info)
        try:
            config = self._build_session_config(item, info, extra_skills=filtered_skills)
            effective_timeout = (
                info.timeout_minutes if info.timeout_minutes is not None else self._settings.task_timeout_minutes
            )
            try:
                if item.session_id:
                    session_id = await vendor.resume(item.session_id, config)
                else:
                    session_id = await vendor.run(config)
                    await self._db.update_queue_item(item.id, status="running", session_id=session_id)

                try:
                    async with asyncio.timeout(effective_timeout * 60):
                        record = await vendor.wait(session_id)
                    final = record.status if record else "failed"
                    queue_status = final if final in ("completed", "failed", "killed") else "failed"
                except TimeoutError:
                    logger.warning(
                        "zombie %s [%s] timed out after %.1f minutes",
                        item.id,
                        info.label,
                        effective_timeout,
                    )
                    await vendor.kill(session_id)
                    queue_status = "failed"
            except Exception:
                logger.exception("zombie %s [%s] raised an error", item.id, info.label)
                queue_status = "failed"

            await self._db.update_queue_item(item.id, status=queue_status, ended_at=datetime.now(UTC))
            logger.info("zombie %s [%s] → %s", item.id, info.label, queue_status)
        finally:
            if tmp_skills_dir:
                shutil.rmtree(tmp_skills_dir, ignore_errors=True)

    # ── internal loop ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            await self._semaphore.acquire()
            item = await self._db.dequeue_next()
            if item:
                task = asyncio.create_task(self._dispatch(item))
                self._dispatch_tasks.add(task)
                task.add_done_callback(self._dispatch_tasks.discard)
            else:
                self._semaphore.release()
                await asyncio.sleep(self._poll_interval)

    async def _dispatch(self, item: QueueItem) -> None:
        info = await self._resolve_agent(item.agent_id)
        # Determine the effective workdir for serialisation: item overrides agent.
        # If neither specifies one, use item.id as a unique key so the task never
        # blocks other tasks (each temp-dir session is independent).
        workdir = item.workdir or (info.workdir if info else None) or item.id
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

        filtered_skills, tmp_skills_dir = self._filter_skills_to_tmpdir(info.skill_globs, item, info)
        try:
            config = self._build_session_config(item, info, extra_skills=filtered_skills)
            effective_timeout = (
                info.timeout_minutes if info.timeout_minutes is not None else self._settings.task_timeout_minutes
            )
            try:
                session_id = await vendor.run(config)
                await self._db.update_queue_item(item.id, status="running", session_id=session_id)

                try:
                    async with asyncio.timeout(effective_timeout * 60):
                        record = await vendor.wait(session_id)
                    final = record.status if record else "failed"
                    queue_status = final if final in ("completed", "failed", "killed") else "failed"
                except TimeoutError:
                    logger.warning("queue %s [%s] timed out after %.1f minutes", item.id, info.label, effective_timeout)
                    await vendor.kill(session_id)
                    queue_status = "failed"
            except Exception:
                logger.exception("queue %s [%s] raised an error", item.id, info.label)
                queue_status = "failed"

            await self._db.update_queue_item(item.id, status=queue_status, ended_at=datetime.now(UTC))
            logger.info("queue %s [%s] → %s", item.id, info.label, queue_status)
        finally:
            if tmp_skills_dir:
                shutil.rmtree(tmp_skills_dir, ignore_errors=True)

    def _build_session_config(
        self,
        item: QueueItem,
        info: _AgentInfo,
        extra_skills: list[SkillConfig] | None = None,
    ) -> SessionConfig:
        """Global MCPs/skills from settings merged with agent-specific ones."""
        merged_mcp = {**self._settings.mcp_servers, **info.mcp_servers}
        merged_skills: list = list(self._settings.skills) + list(info.skills)
        if extra_skills:
            merged_skills = merged_skills + extra_skills
        # item.workdir takes priority over the agent-level default; None means
        # BaseVendor.run() will create a temporary directory for this session.
        workdir = item.workdir if item.workdir is not None else info.workdir
        return SessionConfig(
            prompt=item.prompt,
            model=info.model,
            workdir=workdir,
            mcp_servers=merged_mcp,
            skills=merged_skills,
        )

    def _filter_skills_to_tmpdir(
        self,
        skill_globs: list[str],
        item: QueueItem,
        info: _AgentInfo,
    ) -> tuple[list[SkillConfig], str | None]:
        """Filter `.agents/skills/` directories by glob patterns and copy matches to a temp dir.

        Determines the effective workdir from *item* and *info* (same priority as
        :meth:`_build_session_config`), then scans ``<workdir>/.agents/skills/`` for
        **subdirectories**.  Each directory whose name matches **any** of the *skill_globs*
        patterns is copied into a freshly created temporary directory placed inside *workdir*
        so that skill paths can be expressed as ``./``-relative references.

        Returns a ``(skills, tmp_dir_path)`` tuple.  *skills* is a list of
        :class:`SkillConfig` objects whose ``path`` is a ``./``-prefixed relative path
        from the session workdir.  *tmp_dir_path* is the absolute path of the created
        temporary directory, or ``None`` when no directories matched (and therefore no
        directory was created).  The caller is responsible for removing *tmp_dir_path*
        once the session has finished.

        If *skill_globs* is empty, the skills directory does not exist, or no directories
        match the patterns, ``([], None)`` is returned.
        """
        if not skill_globs:
            return [], None

        workdir = item.workdir if item.workdir is not None else info.workdir
        base = Path(workdir) if workdir else Path.cwd()
        skills_dir = base / ".agents" / "skills"
        if not skills_dir.is_dir():
            return [], None

        matches = [
            d
            for d in skills_dir.iterdir()
            if d.is_dir() and any(fnmatch.fnmatch(d.name, pattern) for pattern in skill_globs)
        ]
        if not matches:
            return [], None

        tmp_dir = Path(tempfile.mkdtemp(prefix=".skills-", dir=base))
        result: list[SkillConfig] = []
        try:
            for src in matches:
                dst = tmp_dir / src.name
                try:
                    shutil.copytree(src, dst)
                except OSError:
                    logger.warning(
                        "skill_globs: failed to copy skill directory %s for agent %s",
                        src.name,
                        info.label,
                    )
                    raise
                result.append(SkillConfig(name=src.name, path=f"./{tmp_dir.name}/{src.name}"))
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        logger.debug("skill_globs filtered %d skill(s) into %s", len(result), tmp_dir)
        return result, str(tmp_dir)

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
                timeout_minutes=agent_s.task_timeout_minutes,
                skill_globs=list(agent_s.skill_globs),
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
