"""Integration tests for OrchestratorDB — queue, memory, cron state."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_database import OrchestratorDB


@pytest.fixture
def db(tmp_path):
    db = OrchestratorDB(tmp_path / "orch.db")
    db.connect()
    yield db
    db.close()


# ── queue ─────────────────────────────────────────────────────────────────────


def test_enqueue_and_dequeue(db):
    # Use a direct agent_id (agents are stored separately; queue does not enforce it at DB layer)
    agent_id = "test-agent-1"

    item = db.enqueue(agent_id, "Do the task")
    assert item.status == "pending"
    assert item.agent_id == agent_id
    assert item.prompt == "Do the task"

    dequeued = db.dequeue_next()
    assert dequeued is not None
    assert dequeued.id == item.id

    # The DB row is updated to "running"; re-fetch to confirm
    refreshed = db.get_queue_item(item.id)
    assert refreshed is not None
    assert refreshed.status == "running"

    # No more pending items; next dequeue returns nothing
    assert db.dequeue_next() is None


def test_dequeue_fifo_order(db):
    agent_id = "test-agent-1"
    item1 = db.enqueue(agent_id, "first")
    item2 = db.enqueue(agent_id, "second")

    d1 = db.dequeue_next()
    d2 = db.dequeue_next()
    assert d1 is not None
    assert d2 is not None
    assert d1.id == item1.id
    assert d2.id == item2.id


def test_cancel_queue_item(db):
    agent_id = "test-agent-1"
    item = db.enqueue(agent_id, "cancelable task")
    db.cancel_queue_item(item.id)

    result = db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "cancelled"

    # cancelled items should not be dequeued
    assert db.dequeue_next() is None


def test_update_queue_item(db):
    agent_id = "test-agent-1"
    item = db.enqueue(agent_id, "updatable task")

    ended = datetime.now(UTC)
    db.update_queue_item(item.id, status="completed", session_id="sess-xyz", ended_at=ended)

    result = db.get_queue_item(item.id)
    assert result is not None
    assert result.status == "completed"
    assert result.session_id == "sess-xyz"
    assert result.ended_at is not None


def test_has_duplicate_pending(db):
    agent_id = "test-agent-1"
    db.enqueue(agent_id, "same prompt")

    assert db.has_duplicate_pending(agent_id, "same prompt") is True
    assert db.has_duplicate_pending(agent_id, "different prompt") is False


def test_list_queue_with_filters(db):
    agent_id = "test-agent-1"
    db.enqueue(agent_id, "task1")
    item2 = db.enqueue(agent_id, "task2")
    db.cancel_queue_item(item2.id)

    pending = db.list_queue(status="pending")
    assert len(pending) == 1


def test_cleanup_old_completed_items_by_count(db):
    """Test that cleanup keeps only the most recent N completed items."""
    agent_id = "test-agent-1"

    # Create 20 completed items
    for i in range(20):
        item = db.enqueue(agent_id, f"task {i}")
        db.update_queue_item(item.id, status="completed", ended_at=datetime.now(UTC))

    # Cleanup should keep only 15 most recent
    deleted = db.cleanup_old_completed_items(max_items=15, max_age_days=365)
    assert deleted == 5

    # Verify only 15 items remain
    completed = db.list_queue(status="completed")
    assert len(completed) == 15


def test_cleanup_old_completed_items_by_age(db):
    """Test that cleanup removes items older than max_age_days."""
    agent_id = "test-agent-1"
    now = datetime.now(UTC)

    # Create items with different ages
    old_item = db.enqueue(agent_id, "old task")
    old_date = now - timedelta(days=10)
    db.update_queue_item(old_item.id, status="completed", ended_at=old_date)

    recent_item = db.enqueue(agent_id, "recent task")
    db.update_queue_item(recent_item.id, status="completed", ended_at=now)

    # Cleanup items older than 7 days
    deleted = db.cleanup_old_completed_items(max_items=100, max_age_days=7)
    assert deleted == 1

    # Verify only recent item remains
    completed = db.list_queue(status="completed")
    assert len(completed) == 1
    assert completed[0].id == recent_item.id


def test_cleanup_respects_both_limits(db):
    """Test that cleanup applies both count and age limits."""
    agent_id = "test-agent-1"
    now = datetime.now(UTC)

    # Create 10 old items (> 7 days old)
    for i in range(10):
        item = db.enqueue(agent_id, f"old task {i}")
        old_date = now - timedelta(days=10)
        db.update_queue_item(item.id, status="completed", ended_at=old_date)

    # Create 10 recent items
    for i in range(10):
        item = db.enqueue(agent_id, f"recent task {i}")
        db.update_queue_item(item.id, status="completed", ended_at=now)

    # Cleanup with max_items=15 and max_age_days=7
    # Should delete all 10 old items (by age) and keep all 10 recent (within both limits)
    deleted = db.cleanup_old_completed_items(max_items=15, max_age_days=7)
    assert deleted == 10

    # Verify only recent items remain
    completed = db.list_queue(status="completed")
    assert len(completed) == 10
    assert all("recent" in item.prompt for item in completed)


def test_cleanup_only_affects_completed_status(db):
    """Test that cleanup only removes completed items, not other statuses."""
    agent_id = "test-agent-1"
    now = datetime.now(UTC)
    old_date = now - timedelta(days=10)

    # Create items with various statuses, all old
    completed_item = db.enqueue(agent_id, "completed task")
    db.update_queue_item(completed_item.id, status="completed", ended_at=old_date)

    failed_item = db.enqueue(agent_id, "failed task")
    db.update_queue_item(failed_item.id, status="failed", ended_at=old_date)

    cancelled_item = db.enqueue(agent_id, "cancelled task")
    db.update_queue_item(cancelled_item.id, status="cancelled", ended_at=old_date)

    # Also create a pending item (not marked as old since it's not ended)
    db.enqueue(agent_id, "pending task")

    # Cleanup should only affect completed items
    deleted = db.cleanup_old_completed_items(max_items=0, max_age_days=7)
    assert deleted == 1

    # Verify other items still exist
    all_items = db.list_queue()
    assert len(all_items) == 3
    assert any(item.status == "failed" for item in all_items)
    assert any(item.status == "cancelled" for item in all_items)
    assert any(item.status == "pending" for item in all_items)


def test_cleanup_returns_zero_when_nothing_to_delete(db):
    """Test that cleanup returns 0 when no items need deletion."""
    agent_id = "test-agent-1"

    # Create only 5 completed items
    for i in range(5):
        item = db.enqueue(agent_id, f"task {i}")
        db.update_queue_item(item.id, status="completed", ended_at=datetime.now(UTC))

    # Cleanup with limit of 15 should delete nothing
    deleted = db.cleanup_old_completed_items(max_items=15, max_age_days=7)
    assert deleted == 0

    # All items should still exist
    completed = db.list_queue(status="completed")
    assert len(completed) == 5


def test_list_queue_by_agent(db):
    a1 = "agent-1"
    a2 = "agent-2"
    db.enqueue(a1, "t1")
    db.enqueue(a2, "t2")
    db.enqueue(a1, "t3")

    items = db.list_queue(agent_id=a1)
    assert len(items) == 2
    assert all(i.agent_id == a1 for i in items)


# ── memory ────────────────────────────────────────────────────────────────────


def test_save_and_get_memory(db):
    agent_id = "test-agent-1"
    mem = db.save_memory(agent_id, "key insight", "The answer is 42")

    assert mem.id
    assert mem.agent_id == agent_id
    assert mem.description == "key insight"
    assert mem.content == "The answer is 42"

    fetched = db.get_memory(mem.id)
    assert fetched is not None
    assert fetched.content == "The answer is 42"


def test_delete_memory(db):
    agent_id = "test-agent-1"
    mem = db.save_memory(agent_id, "desc", "content")
    deleted = db.delete_memory(mem.id)
    assert deleted is True
    assert db.get_memory(mem.id) is None

    # Deleting non-existent returns False
    assert db.delete_memory("nonexistent") is False


def test_list_memories(db):
    a1 = "agent-1"
    a2 = "agent-2"
    db.save_memory(a1, "d1", "c1")
    db.save_memory(a1, "d2", "c2")
    db.save_memory(a2, "d3", "c3")

    all_mems = db.list_memories()
    assert len(all_mems) == 3

    a1_mems = db.list_memories(agent_id=a1)
    assert len(a1_mems) == 2


def test_enqueue_agent_nickname_on_agent(db):
    # Agents are now only in TOML, not in DB, so we just test that enqueue works with any agent_id
    agent_id = "my-agent-with-nick"
    item = db.enqueue(agent_id, "some task")
    assert item.agent_id == agent_id


def test_enqueue_with_workdir(db):
    agent_id = "test-agent-1"
    item = db.enqueue(agent_id, "task with workdir", workdir="/my/project")
    assert item.workdir == "/my/project"

    fetched = db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.workdir == "/my/project"


def test_enqueue_without_workdir_creates_temp_dir(db):
    agent_id = "test-agent-1"
    item = db.enqueue(agent_id, "task no workdir")
    assert item.workdir is not None
    assert Path(item.workdir).exists()

    fetched = db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.workdir == item.workdir


def test_sessions_table_accessible_from_orchestrator_db(db):
    """OrchestratorDB inherits SessionHistoryDB; sessions table should work."""
    record = SessionRecord(
        id="01JTEST0000000000000000001",
        vendor="test",
        prompt="hello",
        workdir=".",
        started_at=datetime.now(UTC),
        status="running",
    )
    db.save(record)
    fetched = db.get(record.id)
    assert fetched is not None
    assert fetched.vendor == "test"


# ── depends_on ────────────────────────────────────────────────────────────────


def test_enqueue_with_depends_on(db):
    agent_id = "test-agent-1"
    dep = db.enqueue(agent_id, "dependency task")
    item = db.enqueue(agent_id, "dependent task", depends_on=[dep.id])

    assert item.depends_on == [dep.id]
    fetched = db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.depends_on == [dep.id]


def test_enqueue_without_depends_on_defaults_to_empty(db):
    agent_id = "test-agent-1"
    item = db.enqueue(agent_id, "independent task")
    assert item.depends_on == []

    fetched = db.get_queue_item(item.id)
    assert fetched is not None
    assert fetched.depends_on == []


def test_dequeue_skips_item_with_pending_dep(db):
    agent_id = "test-agent-1"
    dep = db.enqueue(agent_id, "dep task")
    db.enqueue(agent_id, "blocked task", depends_on=[dep.id])

    # dep is still pending, so blocked task should not be dequeued
    dequeued = db.dequeue_next()
    assert dequeued is not None
    assert dequeued.id == dep.id  # only the dep is ready

    # Now nothing else is dequeue-able (blocked task dep is running, not completed)
    assert db.dequeue_next() is None


def test_dequeue_claims_item_when_dep_completed(db):
    agent_id = "test-agent-1"
    dep = db.enqueue(agent_id, "dep task")
    item = db.enqueue(agent_id, "blocked task", depends_on=[dep.id])

    # Complete the dependency
    db.update_queue_item(dep.id, status="completed")

    dequeued = db.dequeue_next()
    assert dequeued is not None
    assert dequeued.id == item.id


def test_dequeue_auto_fails_item_when_dep_failed(db):
    agent_id = "test-agent-1"
    dep = db.enqueue(agent_id, "dep task")
    item = db.enqueue(agent_id, "blocked task", depends_on=[dep.id])

    db.update_queue_item(dep.id, status="failed")

    # Trying to dequeue should auto-fail the blocked item and return None
    result = db.dequeue_next()
    assert result is None

    failed = db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"


def test_dequeue_auto_fails_item_when_dep_cancelled(db):
    agent_id = "test-agent-1"
    dep = db.enqueue(agent_id, "dep task")
    item = db.enqueue(agent_id, "blocked task", depends_on=[dep.id])

    db.cancel_queue_item(dep.id)

    result = db.dequeue_next()
    assert result is None

    failed = db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"


def test_dequeue_auto_fails_item_when_dep_missing(db):
    agent_id = "test-agent-1"
    item = db.enqueue(agent_id, "blocked task", depends_on=["nonexistent-id"])

    result = db.dequeue_next()
    assert result is None

    failed = db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"


def test_list_queue_includes_depends_on(db):
    agent_id = "test-agent-1"
    dep = db.enqueue(agent_id, "dep")
    item = db.enqueue(agent_id, "dependent", depends_on=[dep.id])

    items = db.list_queue()
    by_id = {i.id: i for i in items}
    assert by_id[dep.id].depends_on == []
    assert by_id[item.id].depends_on == [dep.id]
