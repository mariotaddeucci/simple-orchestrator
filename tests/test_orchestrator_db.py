"""Integration tests for OrchestratorDB — agents, queue, memory, cron state."""

from datetime import UTC, datetime

import pytest

from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.models.session import SessionRecord


@pytest.fixture
async def db(tmp_path):
    db = OrchestratorDB(tmp_path / "orch.db")
    await db.connect()
    yield db
    await db.close()


# ── agents ────────────────────────────────────────────────────────────────────


async def test_register_and_get_agent(db):
    agent = await db.register_agent(
        name="Reviewer",
        prompt="You review code.",
        vendor="claude",
        workdir="/workspace",
        model="claude-opus",
        nickname="reviewer",
    )
    assert agent.id
    assert agent.name == "Reviewer"
    assert agent.vendor == "claude"
    assert agent.nickname == "reviewer"

    fetched = await db.get_agent(agent.id)
    assert fetched is not None
    assert fetched.id == agent.id
    assert fetched.model == "claude-opus"


async def test_get_agent_missing_returns_none(db):
    result = await db.get_agent("nonexistent")
    assert result is None


async def test_list_agents(db):
    await db.register_agent(name="A1", prompt="p1", vendor="claude")
    await db.register_agent(name="A2", prompt="p2", vendor="openai")
    await db.register_agent(name="A3", prompt="p3", vendor="claude")

    all_agents = await db.list_agents()
    assert len(all_agents) == 3

    claude_agents = await db.list_agents(vendor="claude")
    assert len(claude_agents) == 2
    assert all(a.vendor == "claude" for a in claude_agents)


async def test_delete_agent(db):
    agent = await db.register_agent(name="Temp", prompt="tmp", vendor="v1")
    await db.delete_agent(agent.id)
    assert await db.get_agent(agent.id) is None


# ── queue ─────────────────────────────────────────────────────────────────────


async def test_enqueue_and_dequeue(db):
    agent = await db.register_agent(name="Worker", prompt="work prompt", vendor="claude")

    item = await db.enqueue(agent.id, "Do the task")
    assert item.status == "pending"
    assert item.agent_id == agent.id
    assert item.prompt == "Do the task"

    dequeued = await db.dequeue_next()
    assert dequeued is not None
    assert dequeued.id == item.id

    # The DB row is updated to "running"; re-fetch to confirm
    refreshed = await db.get_queue_item(item.id)
    assert refreshed is not None
    assert refreshed.status == "running"

    # No more pending items; next dequeue returns nothing
    assert await db.dequeue_next() is None


async def test_dequeue_fifo_order(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item1 = await db.enqueue(agent.id, "first")
    item2 = await db.enqueue(agent.id, "second")

    d1 = await db.dequeue_next()
    d2 = await db.dequeue_next()
    assert d1 is not None
    assert d2 is not None
    assert d1.id == item1.id
    assert d2.id == item2.id


async def test_cancel_queue_item(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item = await db.enqueue(agent.id, "cancelable task")
    await db.cancel_queue_item(item.id)

    result = await db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "cancelled"

    # cancelled items should not be dequeued
    assert await db.dequeue_next() is None


async def test_update_queue_item(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item = await db.enqueue(agent.id, "updatable task")

    ended = datetime.now(UTC)
    await db.update_queue_item(item.id, status="completed", session_id="sess-xyz", ended_at=ended)

    result = await db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "completed"
    assert result.session_id == "sess-xyz"
    assert result.ended_at is not None


async def test_has_duplicate_pending(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    await db.enqueue(agent.id, "same prompt")

    assert await db.has_duplicate_pending(agent.id, "same prompt") is True
    assert await db.has_duplicate_pending(agent.id, "different prompt") is False


async def test_list_queue_with_filters(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    await db.enqueue(agent.id, "task1")
    item2 = await db.enqueue(agent.id, "task2")
    await db.cancel_queue_item(item2.id)

    pending = await db.list_queue(status="pending")
    assert len(pending) == 1

    cancelled = await db.list_queue(status="cancelled")
    assert len(cancelled) == 1


async def test_list_queue_by_agent(db):
    a1 = await db.register_agent(name="A1", prompt="p", vendor="v")
    a2 = await db.register_agent(name="A2", prompt="p", vendor="v")
    await db.enqueue(a1.id, "t1")
    await db.enqueue(a2.id, "t2")
    await db.enqueue(a1.id, "t3")

    items = await db.list_queue(agent_id=a1.id)
    assert len(items) == 2
    assert all(i.agent_id == a1.id for i in items)


# ── memory ────────────────────────────────────────────────────────────────────


async def test_save_and_get_memory(db):
    agent = await db.register_agent(name="A", prompt="p", vendor="v")
    mem = await db.save_memory(agent.id, "key insight", "The answer is 42")

    assert mem.id
    assert mem.agent_id == agent.id
    assert mem.description == "key insight"
    assert mem.content == "The answer is 42"

    fetched = await db.get_memory(mem.id)
    assert fetched is not None
    assert fetched.content == "The answer is 42"


async def test_delete_memory(db):
    agent = await db.register_agent(name="A", prompt="p", vendor="v")
    mem = await db.save_memory(agent.id, "desc", "content")
    deleted = await db.delete_memory(mem.id)
    assert deleted is True
    assert await db.get_memory(mem.id) is None

    # Deleting non-existent returns False
    assert await db.delete_memory("nonexistent") is False


async def test_list_memories(db):
    a1 = await db.register_agent(name="A1", prompt="p", vendor="v")
    a2 = await db.register_agent(name="A2", prompt="p", vendor="v")
    await db.save_memory(a1.id, "d1", "c1")
    await db.save_memory(a1.id, "d2", "c2")
    await db.save_memory(a2.id, "d3", "c3")

    all_mems = await db.list_memories()
    assert len(all_mems) == 3

    a1_mems = await db.list_memories(agent_id=a1.id)
    assert len(a1_mems) == 2


# ── cron state ────────────────────────────────────────────────────────────────


async def test_cron_state(db):
    assert await db.get_cron_last_run("key1") is None

    now = datetime.now(UTC).replace(microsecond=0)
    await db.set_cron_last_run("key1", now)

    result = await db.get_cron_last_run("key1")
    assert result is not None
    assert result.replace(tzinfo=UTC) == now


async def test_cron_state_upsert(db):
    t1 = datetime(2024, 1, 1, tzinfo=UTC)
    t2 = datetime(2024, 6, 1, tzinfo=UTC)
    await db.set_cron_last_run("k", t1)
    await db.set_cron_last_run("k", t2)

    result = await db.get_cron_last_run("k")
    assert result is not None
    assert result.replace(tzinfo=UTC) == t2


async def test_enqueue_agent_nickname_propagated(db):
    agent = await db.register_agent(name="Named Agent", prompt="p", vendor="v", nickname="my-nick")
    item = await db.enqueue(agent.id, "some task")
    assert item.agent_nickname == "my-nick"


async def test_enqueue_with_workdir(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item = await db.enqueue(agent.id, "task with workdir", workdir="/my/project")
    assert item.workdir == "/my/project"

    fetched = await db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.workdir == "/my/project"


async def test_enqueue_without_workdir_is_none(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item = await db.enqueue(agent.id, "task no workdir")
    assert item.workdir is None

    fetched = await db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.workdir is None


async def test_sessions_table_accessible_from_orchestrator_db(db):
    """OrchestratorDB inherits SessionHistoryDB; sessions table should work."""
    record = SessionRecord(
        id="01JTEST0000000000000000001",
        vendor="test",
        prompt="hello",
        workdir=".",
        started_at=datetime.now(UTC),
        status="running",
    )
    await db.save(record)
    fetched = await db.get(record.id)
    assert fetched is not None
    assert fetched.vendor == "test"


# ── depends_on ────────────────────────────────────────────────────────────────


async def test_enqueue_with_depends_on(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    dep = await db.enqueue(agent.id, "dependency task")
    item = await db.enqueue(agent.id, "dependent task", depends_on=[dep.id])

    assert item.depends_on == [dep.id]
    fetched = await db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.depends_on == [dep.id]


async def test_enqueue_without_depends_on_defaults_to_empty(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item = await db.enqueue(agent.id, "independent task")
    assert item.depends_on == []

    fetched = await db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.depends_on == []


async def test_dequeue_skips_item_with_pending_dep(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    dep = await db.enqueue(agent.id, "dep task")
    await db.enqueue(agent.id, "blocked task", depends_on=[dep.id])

    # dep is still pending, so blocked task should not be dequeued
    dequeued = await db.dequeue_next()
    assert dequeued is not None
    assert dequeued.id == dep.id  # only the dep is ready

    # Now nothing else is dequeue-able (blocked task dep is running, not completed)
    assert await db.dequeue_next() is None


async def test_dequeue_claims_item_when_dep_completed(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    dep = await db.enqueue(agent.id, "dep task")
    item = await db.enqueue(agent.id, "blocked task", depends_on=[dep.id])

    # Complete the dependency
    await db.update_queue_item(dep.id, status="completed")

    dequeued = await db.dequeue_next()
    assert dequeued is not None
    assert dequeued.id == item.id


async def test_dequeue_auto_fails_item_when_dep_failed(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    dep = await db.enqueue(agent.id, "dep task")
    item = await db.enqueue(agent.id, "blocked task", depends_on=[dep.id])

    await db.update_queue_item(dep.id, status="failed")

    # Trying to dequeue should auto-fail the blocked item and return None
    result = await db.dequeue_next()
    assert result is None

    failed = await db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"


async def test_dequeue_auto_fails_item_when_dep_cancelled(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    dep = await db.enqueue(agent.id, "dep task")
    item = await db.enqueue(agent.id, "blocked task", depends_on=[dep.id])

    await db.cancel_queue_item(dep.id)

    result = await db.dequeue_next()
    assert result is None

    failed = await db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"


async def test_dequeue_auto_fails_item_when_dep_missing(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    item = await db.enqueue(agent.id, "blocked task", depends_on=["nonexistent-id"])

    result = await db.dequeue_next()
    assert result is None

    failed = await db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"


async def test_list_queue_includes_depends_on(db):
    agent = await db.register_agent(name="W", prompt="p", vendor="v")
    dep = await db.enqueue(agent.id, "dep")
    item = await db.enqueue(agent.id, "dependent", depends_on=[dep.id])

    items = await db.list_queue()
    by_id = {i.id: i for i in items}
    assert by_id[dep.id].depends_on == []
    assert by_id[item.id].depends_on == [dep.id]
