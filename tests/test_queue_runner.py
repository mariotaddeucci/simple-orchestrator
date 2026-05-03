"""Integration tests for QueueRunner."""

import asyncio
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.models.mcp import McpStdioConfig
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.queue_item import QueueItem
from simple_orchestrator.models.session import SessionConfig, SessionRecord
from simple_orchestrator.models.skill import SkillConfig
from simple_orchestrator.queue_runner import QueueRunner, _AgentInfo
from simple_orchestrator.settings import OrchestratorSettings
from simple_orchestrator.vendors.base import BaseVendor

# 0.01 seconds expressed in minutes — used to trigger timeouts quickly in tests
_TEST_TIMEOUT_MINUTES = 1 / 6000


class FakeVendor(BaseVendor):
    """Minimal vendor that immediately completes sessions."""

    def __init__(self, db: SessionHistoryDB, *, fail: bool = False) -> None:
        super().__init__(db)
        self._fail = fail
        self.executed_prompts: list[str] = []

    @property
    def vendor_name(self) -> str:
        return "fake"

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        self.executed_prompts.append(config.prompt)
        if self._fail:
            raise RuntimeError("deliberate failure")
        await asyncio.sleep(0)  # yield control

    async def _vendor_kill(self, session_id: str) -> None:
        pass

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        async def _gen() -> AsyncIterator[Any]:
            yield config.prompt

        return _gen()

    async def list_models(self) -> list[ModelInfo]:
        return []


@pytest.fixture
async def orch_db(tmp_path):
    db = OrchestratorDB(tmp_path / "orch.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def settings():
    return OrchestratorSettings(max_active_sessions=2)


async def test_run_until_empty_completes_all_items(orch_db, settings):
    vendor = FakeVendor(orch_db)
    agent = await orch_db.register_agent(name="A", prompt="p", vendor="fake")
    await orch_db.enqueue(agent.id, "task one")
    await orch_db.enqueue(agent.id, "task two")

    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    await runner.run_until_empty()

    # Allow background _on_done callbacks to fire
    await asyncio.sleep(0.1)

    items = await orch_db.list_queue()
    assert len(items) == 2
    assert all(i.status in ("completed", "running") for i in items)
    assert len(vendor.executed_prompts) == 2


async def test_run_until_empty_no_items(orch_db, settings):
    vendor = FakeVendor(orch_db)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    # Should return immediately without error
    await runner.run_until_empty()


async def test_process_fails_when_agent_not_found(orch_db, settings):
    vendor = FakeVendor(orch_db)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)

    # Enqueue directly (bypass register_agent so agent is unknown)
    ghost_agent_id = str(ULID())
    item = QueueItem(
        id=str(ULID()),
        agent_id=ghost_agent_id,
        prompt="ghost task",
        status="running",  # already claimed
        created_at=datetime.now(UTC),
    )
    # Process directly via _process to test the "agent not found" path
    await runner._process(item, None)

    # No vendor call should have happened
    assert len(vendor.executed_prompts) == 0


async def test_process_fails_when_vendor_not_registered(orch_db, settings):
    runner = QueueRunner(orch_db, {}, settings=settings)  # no vendors
    agent = await orch_db.register_agent(name="A", prompt="p", vendor="fake")
    item = await orch_db.enqueue(agent.id, "task")
    dequeued = await orch_db.dequeue_next()
    assert dequeued is not None

    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir=".",
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        timeout_minutes=None,
    )
    await runner._process(dequeued, info)

    result = await orch_db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "failed"


async def test_start_and_stop(orch_db, settings):
    vendor = FakeVendor(orch_db)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings, poll_interval=0.05)
    await runner.start()
    assert runner._running is True
    await asyncio.sleep(0.1)
    await runner.stop()
    assert runner._running is False


async def test_active_count(orch_db, settings):
    vendor = FakeVendor(orch_db)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    # Initially zero active
    assert runner.active_count == 0


async def test_build_session_config_merges_mcp_and_skills(orch_db):
    global_mcp = {"global_tool": McpStdioConfig(type="stdio", command="global-cmd", args=[])}
    settings = OrchestratorSettings(max_active_sessions=1, mcp_servers=global_mcp, skills=["global-skill"])

    vendor = FakeVendor(orch_db)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)

    agent_mcp = {"agent_tool": McpStdioConfig(type="stdio", command="agent-cmd", args=[])}
    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir=".",
        prompt="p",
        model=None,
        mcp_servers=agent_mcp,
        skills=["agent-skill"],
        timeout_minutes=None,
    )

    item = QueueItem(
        id=str(ULID()),
        agent_id="any",
        prompt="merged task",
        status="running",
        created_at=datetime.now(UTC),
    )

    config = runner._build_session_config(item, info)
    assert "global_tool" in config.mcp_servers
    assert "agent_tool" in config.mcp_servers
    assert "global-skill" in config.skills
    assert "agent-skill" in config.skills
    assert config.prompt == "merged task"


async def test_build_session_config_item_workdir_overrides_agent(orch_db):
    """item.workdir takes priority over the agent-level workdir."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir="/agent-dir",
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        timeout_minutes=None,
    )
    item = QueueItem(
        id=str(ULID()),
        agent_id="any",
        prompt="task",
        workdir="/task-dir",
        status="running",
        created_at=datetime.now(UTC),
    )

    config = runner._build_session_config(item, info)
    assert config.workdir == "/task-dir"


async def test_build_session_config_falls_back_to_agent_workdir(orch_db):
    """When item has no workdir, the agent workdir is used."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir="/agent-dir",
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        timeout_minutes=None,
    )
    item = QueueItem(
        id=str(ULID()),
        agent_id="any",
        prompt="task",
        status="running",
        created_at=datetime.now(UTC),
    )

    config = runner._build_session_config(item, info)
    assert config.workdir == "/agent-dir"


async def test_build_session_config_no_workdir_is_none(orch_db):
    """When neither item nor agent specifies a workdir, config.workdir is None."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir=None,
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        timeout_minutes=None,
    )
    item = QueueItem(
        id=str(ULID()),
        agent_id="any",
        prompt="task",
        status="running",
        created_at=datetime.now(UTC),
    )

    config = runner._build_session_config(item, info)
    assert config.workdir is None


class SlowVendor(FakeVendor):
    """Vendor that hangs indefinitely until cancelled."""

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        self.executed_prompts.append(config.prompt)
        await asyncio.sleep(9999)


async def test_process_times_out_and_marks_failed(orch_db):
    """A session that exceeds its timeout is killed and the queue item marked failed."""
    vendor = SlowVendor(orch_db)
    agent = await orch_db.register_agent(name="Slow", prompt="p", vendor="fake")
    item = await orch_db.enqueue(agent.id, "slow task")
    dequeued = await orch_db.dequeue_next()
    assert dequeued is not None

    # Use a tiny timeout (1/100th of a second) so the test runs fast
    info = _AgentInfo(
        label="Slow",
        vendor="fake",
        workdir=None,
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        timeout_minutes=_TEST_TIMEOUT_MINUTES,
    )
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)

    await runner._process(dequeued, info)

    result = await orch_db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "failed"


async def test_global_timeout_used_when_agent_has_none(orch_db):
    """When agent timeout_minutes is None, the global settings timeout is used."""
    vendor = SlowVendor(orch_db)
    agent = await orch_db.register_agent(name="Slow2", prompt="p", vendor="fake")
    item = await orch_db.enqueue(agent.id, "slow task 2")
    dequeued = await orch_db.dequeue_next()
    assert dequeued is not None

    info = _AgentInfo(
        label="Slow2",
        vendor="fake",
        workdir=None,
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        timeout_minutes=None,  # falls back to global
    )
    # Global timeout of 0.01 seconds
    settings = OrchestratorSettings(max_active_sessions=1, task_timeout_minutes=_TEST_TIMEOUT_MINUTES)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)

    await runner._process(dequeued, info)

    result = await orch_db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "failed"


# ── zombie resume tests ───────────────────────────────────────────────────────


class ResumingVendor(FakeVendor):
    """Records which session_ids were passed to _run_session, enabling resume detection."""

    def __init__(self, db: SessionHistoryDB) -> None:
        super().__init__(db)
        self.run_session_ids: list[str] = []

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        self.run_session_ids.append(session_id)
        self.executed_prompts.append(config.prompt)
        await asyncio.sleep(0)


async def test_resume_zombie_sessions_resumes_with_existing_session_id(orch_db, settings):
    """Items left in 'running' state are resumed using the saved session_id."""
    vendor = ResumingVendor(orch_db)
    agent = await orch_db.register_agent(name="A", prompt="p", vendor="fake")

    # Simulate a zombie: enqueue, dequeue (→running), link a session_id as if a
    # previous run had started the session but then crashed mid-execution.
    item = await orch_db.enqueue(agent.id, "zombie task")
    await orch_db.dequeue_next()  # transitions item to 'running'
    saved_session_id = str(ULID())
    await orch_db.update_queue_item(item.id, status="running", session_id=saved_session_id)

    # Also create a session record so vendor.resume can update it back to 'running'
    zombie_record = SessionRecord(
        id=saved_session_id,
        vendor="fake",
        prompt="zombie task",
        workdir="/tmp/work",
        started_at=datetime.now(UTC),
        status="running",
    )
    await orch_db.save(zombie_record)

    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    await runner.resume_zombie_sessions()

    # Give background callbacks a moment to fire
    await asyncio.sleep(0.1)

    # The vendor must have been called with the same session_id (resume, not fresh run)
    assert saved_session_id in vendor.run_session_ids

    # The queue item must have been marked completed
    result = await orch_db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "completed"


async def test_resume_zombie_sessions_runs_fresh_when_no_session_id(orch_db, settings):
    """Zombie items with no saved session_id get a brand-new session."""
    vendor = ResumingVendor(orch_db)
    agent = await orch_db.register_agent(name="B", prompt="p", vendor="fake")

    item = await orch_db.enqueue(agent.id, "no-session zombie")
    await orch_db.dequeue_next()
    # Leave session_id as NULL — as if the crash happened before vendor.run() returned

    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    await runner.resume_zombie_sessions()
    await asyncio.sleep(0.1)

    assert len(vendor.executed_prompts) == 1

    result = await orch_db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "completed"


async def test_resume_zombie_sessions_marks_failed_when_agent_missing(orch_db, settings):
    """Zombie items whose agent is gone are marked failed, not re-run."""
    vendor = ResumingVendor(orch_db)
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)

    ghost_agent_id = str(ULID())
    # Directly insert a zombie queue item with an unknown agent
    item_id = str(ULID())
    await orch_db._conn.execute(
        "INSERT INTO queue (id, agent_id, prompt, status, created_at) VALUES (?, ?, ?, 'running', ?)",
        (item_id, ghost_agent_id, "ghost task", datetime.now(UTC).isoformat()),
    )
    await orch_db._conn.commit()

    await runner.resume_zombie_sessions()
    await asyncio.sleep(0.1)

    result = await orch_db.get_queue_item(item_id)
    assert result is not None
    assert result.status == "failed"
    assert len(vendor.executed_prompts) == 0


async def test_start_resumes_zombie_sessions_automatically(orch_db, settings):
    """start() calls resume_zombie_sessions before starting the polling loop."""
    vendor = ResumingVendor(orch_db)
    agent = await orch_db.register_agent(name="C", prompt="p", vendor="fake")

    item = await orch_db.enqueue(agent.id, "startup zombie")
    await orch_db.dequeue_next()

    saved_session_id = str(ULID())
    await orch_db.update_queue_item(item.id, status="running", session_id=saved_session_id)
    await orch_db.save(
        SessionRecord(
            id=saved_session_id,
            vendor="fake",
            prompt="startup zombie",
            workdir="/tmp/work",
            started_at=datetime.now(UTC),
            status="running",
        ),
    )

    # Use a short poll_interval so the background loop doesn't delay the test.
    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings, poll_interval=0.05)
    await runner.start()
    await asyncio.sleep(0.2)
    await runner.stop()

    assert saved_session_id in vendor.run_session_ids


# ── depends_on integration tests ─────────────────────────────────────────────


async def test_run_until_empty_respects_depends_on(orch_db, settings):
    """Dependent task only runs after its dependency is completed."""
    vendor = FakeVendor(orch_db)
    agent = await orch_db.register_agent(name="A", prompt="p", vendor="fake")

    dep = await orch_db.enqueue(agent.id, "first")
    _item = await orch_db.enqueue(agent.id, "second", depends_on=[dep.id])

    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    await runner.run_until_empty()

    items = await orch_db.list_queue()
    assert all(i.status == "completed" for i in items), [i.status for i in items]
    assert vendor.executed_prompts == ["first", "second"]


async def test_run_until_empty_fails_dependent_when_dep_fails(orch_db, settings):
    """Dependent task is auto-failed when its dependency fails."""
    vendor = FakeVendor(orch_db, fail=True)
    agent = await orch_db.register_agent(name="A", prompt="p", vendor="fake")

    dep = await orch_db.enqueue(agent.id, "first-fails")
    item = await orch_db.enqueue(agent.id, "second-blocked", depends_on=[dep.id])

    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    await runner.run_until_empty()

    dep_result = await orch_db.get_queue_item(dep.id)
    assert dep_result is not None
    assert dep_result.status == "failed"

    item_result = await orch_db.get_queue_item(item.id)
    assert item_result is not None
    assert item_result.status == "failed"


async def test_run_until_empty_chain_of_three(orch_db, settings):
    """A → B → C chain runs in order and all complete."""
    vendor = FakeVendor(orch_db)
    agent = await orch_db.register_agent(name="A", prompt="p", vendor="fake")

    a = await orch_db.enqueue(agent.id, "task-a")
    b = await orch_db.enqueue(agent.id, "task-b", depends_on=[a.id])
    c = await orch_db.enqueue(agent.id, "task-c", depends_on=[b.id])

    runner = QueueRunner(orch_db, {"fake": vendor}, settings=settings)
    await runner.run_until_empty()

    for task_id in (a.id, b.id, c.id):
        result = await orch_db.get_queue_item(task_id)
        assert result is not None
        assert result.status == "completed", f"{task_id} has status {result.status}"

    assert vendor.executed_prompts == ["task-a", "task-b", "task-c"]


# ── skill_globs tests ─────────────────────────────────────────────────────────


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create a .agents/skills directory populated with sample skill directories."""
    d = tmp_path / ".agents" / "skills"
    d.mkdir(parents=True)
    # Each skill is a subdirectory
    (d / "coding-helper").mkdir()
    (d / "coding-helper" / "instructions.md").write_text("# Coding helper")
    (d / "coding-reviewer").mkdir()
    (d / "coding-reviewer" / "instructions.md").write_text("# Coding reviewer")
    (d / "security-audit").mkdir()
    (d / "security-audit" / "instructions.md").write_text("# Security audit")
    # A plain file (not a directory) — must be ignored
    (d / "readme.txt").write_text("not a skill")
    return d


def _make_item(workdir: str | None = None) -> QueueItem:
    return QueueItem(
        id=str(ULID()),
        agent_id="any",
        prompt="task",
        workdir=workdir,
        status="running",
        created_at=datetime.now(UTC),
    )


def _make_info(workdir: str | None = None, skill_globs: list[str] | None = None) -> _AgentInfo:
    return _AgentInfo(
        label="A",
        vendor="fake",
        workdir=workdir,
        prompt="p",
        model=None,
        mcp_servers={},
        skills=[],
        skill_globs=skill_globs or [],
    )


async def test_filter_skills_to_tmpdir_basic(orch_db, tmp_path, skills_dir):
    """Glob patterns select only matching skill directories and copy them to a temp dir."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    results, tmp_dir = runner._filter_skills_to_tmpdir(["coding-*"], item, info)

    assert tmp_dir is not None
    assert len(results) == 2
    names = {r.name for r in results}
    assert names == {"coding-helper", "coding-reviewer"}
    for skill in results:
        assert skill.path is not None
        assert skill.path.startswith("./")
        # The skill directory must exist inside the workdir temp dir
        assert (tmp_path / skill.path).is_dir()


async def test_filter_skills_to_tmpdir_multiple_globs(orch_db, tmp_path, skills_dir):
    """Multiple glob patterns are ORed together."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    results, tmp_dir = runner._filter_skills_to_tmpdir(["coding-helper", "security-*"], item, info)

    assert tmp_dir is not None
    names = {r.name for r in results}
    assert names == {"coding-helper", "security-audit"}


async def test_filter_skills_to_tmpdir_no_match(orch_db, tmp_path, skills_dir):
    """Returns an empty list and None when no skill directories match the patterns."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    results, tmp_dir = runner._filter_skills_to_tmpdir(["nonexistent-*"], item, info)

    assert results == []
    assert tmp_dir is None


async def test_filter_skills_to_tmpdir_missing_skills_dir(orch_db, tmp_path):
    """Returns an empty list and None when the .agents/skills directory does not exist."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    results, tmp_dir = runner._filter_skills_to_tmpdir(["*"], item, info)

    assert results == []
    assert tmp_dir is None


async def test_filter_skills_to_tmpdir_empty_globs(orch_db, tmp_path, skills_dir):
    """Returns empty list and None when skill_globs is empty (no filtering requested)."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    results, tmp_dir = runner._filter_skills_to_tmpdir([], item, info)

    assert results == []
    assert tmp_dir is None


async def test_filter_skills_ignores_non_directory_entries(orch_db, tmp_path, skills_dir):
    """Plain files in the skills directory are never included even with wildcard globs."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    results, _tmp_dir = runner._filter_skills_to_tmpdir(["*"], item, info)

    # "readme.txt" is a plain file and must not appear
    assert all(r.name != "readme.txt" for r in results)
    for skill in results:
        assert skill.path is not None
        assert skill.path.startswith("./")


async def test_filter_skills_tmpdir_cleanup(orch_db, tmp_path, skills_dir):
    """The caller can clean up the returned temp directory after the session."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=str(tmp_path))
    info = _make_info()
    _results, tmp_dir = runner._filter_skills_to_tmpdir(["*"], item, info)

    assert tmp_dir is not None
    assert Path(tmp_dir).is_dir()

    shutil.rmtree(tmp_dir, ignore_errors=True)
    assert not Path(tmp_dir).exists()


async def test_filter_skills_uses_info_workdir_when_item_has_none(orch_db, tmp_path, skills_dir):
    """Falls back to agent workdir when item.workdir is None."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    item = _make_item(workdir=None)
    info = _make_info(workdir=str(tmp_path))
    results, tmp_dir = runner._filter_skills_to_tmpdir(["coding-*"], item, info)

    assert tmp_dir is not None
    assert len(results) == 2


async def test_build_session_config_applies_skill_globs(orch_db, tmp_path, skills_dir):
    """_build_session_config with extra_skills merges filtered skills into the session config."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir=str(tmp_path),
        prompt="p",
        model=None,
        mcp_servers={},
        skills=["builtin-skill"],
        skill_globs=["coding-*"],
    )
    item = _make_item(workdir=str(tmp_path))

    filtered_skills, tmp_dir = runner._filter_skills_to_tmpdir(info.skill_globs, item, info)
    try:
        config = runner._build_session_config(item, info, extra_skills=filtered_skills)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    skill_names = [s if isinstance(s, str) else s.name for s in config.skills]
    assert "builtin-skill" in skill_names
    assert "coding-helper" in skill_names
    assert "coding-reviewer" in skill_names
    # security-audit did not match coding-*
    assert "security-audit" not in skill_names

    # Filtered skills carry ./-prefixed relative paths
    path_skills = [s for s in config.skills if isinstance(s, SkillConfig) and s.path is not None]
    assert len(path_skills) == 2
    assert all(s.path is not None and s.path.startswith("./") for s in path_skills)


async def test_build_session_config_no_skill_globs_unchanged(orch_db, tmp_path, skills_dir):
    """When skill_globs is empty no filtering is performed."""
    settings = OrchestratorSettings(max_active_sessions=1)
    runner = QueueRunner(orch_db, {}, settings=settings)

    info = _AgentInfo(
        label="A",
        vendor="fake",
        workdir=str(tmp_path),
        prompt="p",
        model=None,
        mcp_servers={},
        skills=["existing-skill"],
        skill_globs=[],
    )
    item = _make_item()

    config = runner._build_session_config(item, info)

    assert config.skills == ["existing-skill"]
