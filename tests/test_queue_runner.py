"""Integration tests for QueueRunner."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from ulid import ULID

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.models.mcp import McpStdioConfig
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.queue_item import QueueItem
from simple_orchestrator.models.session import SessionConfig
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
    db = OrchestratorDB(str(tmp_path / "orch.db"))
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
