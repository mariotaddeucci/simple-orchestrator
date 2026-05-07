import concurrent.futures
import contextlib
import fnmatch
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .db.orchestrator import OrchestratorDB
from .logging_config import get_internal_logger
from .models.queue_item import QueueItem
from .models.session import SessionConfig
from .models.skill import SkillConfig
from .settings import AgentSettings, OrchestratorSettings
from .vendors.base import BaseVendor

logger = get_internal_logger(__name__)


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
    Runs synchronously in a thread worker. Uses ThreadPoolExecutor for concurrent dispatch.
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
        self._running = False
        self._workdir_locks: dict[str, threading.Lock] = {}
        self._workdir_locks_mutex = threading.Lock()

    @property
    def active_count(self) -> int:
        return len(self._db.list_queue(status="running"))

    def start(self) -> None:
        """Start queue processing loop. Blocks until stop() is called. Call from a thread worker."""
        if self._running:
            return
        self._running = True
        self._resume_zombie_sessions()
        self._loop()

    def stop(self) -> None:
        self._running = False

    def run_until_empty(self) -> None:
        """Drain the queue synchronously. Used in tests."""
        self._resume_zombie_sessions()
        with concurrent.futures.ThreadPoolExecutor(max_workers=self._settings.max_active_sessions) as executor:
            futures: set[concurrent.futures.Future] = set()
            while True:
                done = {f for f in futures if f.done()}
                for f in done:
                    exc = f.exception()
                    if exc:
                        logger.exception("dispatch error", exc_info=exc)
                futures -= done

                if len(futures) < self._settings.max_active_sessions:
                    item = self._db.dequeue_next()
                    if item:
                        futures.add(executor.submit(self._dispatch, item))
                        continue

                if not futures:
                    break

                concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)

    def _resume_zombie_sessions(self) -> None:
        zombie_items = self._db.list_queue(status="running")
        if not zombie_items:
            return
        logger.info("QueueRunner: found %d zombie session(s), re-queuing...", len(zombie_items))
        for item in zombie_items:
            self._db.update_queue_item(item.id, status="pending")

    def _loop(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=self._settings.max_active_sessions) as executor:
            futures: set[concurrent.futures.Future] = set()
            while self._running:
                done = {f for f in futures if f.done()}
                for f in done:
                    exc = f.exception()
                    if exc:
                        logger.exception("dispatch error", exc_info=exc)
                futures -= done

                if len(futures) < self._settings.max_active_sessions:
                    item = self._db.dequeue_next()
                    if item:
                        logger.info("QueueRunner: dequeued item id=%s agent_id=%s", item.id, item.agent_id)
                        futures.add(executor.submit(self._dispatch, item))
                        continue

                time.sleep(self._poll_interval)

    def _get_workdir_lock(self, workdir: str) -> threading.Lock:
        with self._workdir_locks_mutex:
            if workdir not in self._workdir_locks:
                self._workdir_locks[workdir] = threading.Lock()
            return self._workdir_locks[workdir]

    def _dispatch(self, item: QueueItem) -> None:
        logger.info("QueueRunner._dispatch: item id=%s agent_id=%s", item.id, item.agent_id)
        info = self._resolve_agent(item.agent_id)
        workdir = item.workdir or (info.workdir if info else None) or item.id
        with self._get_workdir_lock(workdir):
            self._process(item, info)

    def _process(self, item: QueueItem, info: _AgentInfo | None) -> None:
        if not info:
            logger.error("queue %s: agent '%s' not found in settings", item.id, item.agent_id)
            self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
            return

        vendor = self._vendors.get(info.vendor)
        if not vendor:
            logger.error("queue %s [%s]: vendor '%s' not registered", item.id, info.label, info.vendor)
            self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
            return

        effective_timeout = (
            info.timeout_minutes if info.timeout_minutes is not None else self._settings.task_timeout_minutes
        )
        filtered_skills, tmp_skills_dir = self._filter_skills_to_tmpdir(info.skill_globs, item, info)
        try:
            config = self._build_session_config(item, info, extra_skills=filtered_skills)
            session_id, final_status = vendor.run_sync(config, timeout_minutes=effective_timeout)
            self._db.update_queue_item(item.id, status=final_status, session_id=session_id, ended_at=datetime.now(UTC))
            logger.info("queue %s [%s] -> %s", item.id, info.label, final_status)
            self._cleanup_if_completed(final_status)
        except Exception:
            logger.exception("queue %s [%s] raised an error", item.id, info.label)
            self._db.update_queue_item(item.id, status="failed", ended_at=datetime.now(UTC))
        finally:
            if tmp_skills_dir:
                shutil.rmtree(tmp_skills_dir, ignore_errors=True)

    def _cleanup_if_completed(self, queue_status: str) -> None:
        if queue_status == "completed":
            with contextlib.suppress(Exception):
                deleted = self._db.cleanup_old_completed_items(
                    max_items=self._settings.max_completed_items,
                    max_age_days=self._settings.max_completed_age_days,
                )
                if deleted > 0:
                    logger.debug("Cleanup: removed %d old completed items", deleted)

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
        workdir = item.workdir if item.workdir is not None else info.workdir
        return SessionConfig(
            prompt=item.prompt,
            model=info.model,
            workdir=workdir,
            mcp_servers=merged_mcp,
            skills=merged_skills,
            env={"ORCHESTRATOR_TASK_ID": item.id},
        )

    def _filter_skills_to_tmpdir(
        self,
        skill_globs: list[str],
        item: QueueItem,
        info: _AgentInfo,
    ) -> tuple[list[SkillConfig], str | None]:
        """Filter `.agents/skills/` directories by glob patterns and copy matches to a temp dir."""
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
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise
            result.append(SkillConfig(name=src.name, path=f"./{tmp_dir.name}/{src.name}"))
        logger.debug("skill_globs filtered %d skill(s) into %s", len(result), tmp_dir)
        return result, str(tmp_dir)

    def _resolve_agent(self, agent_id: str) -> _AgentInfo | None:
        """Resolve agent from TOML settings only."""
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

        return None
