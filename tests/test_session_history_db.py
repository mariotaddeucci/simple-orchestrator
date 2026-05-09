"""Integration tests for SessionHistoryDB."""

from datetime import UTC, datetime

import pytest
from simple_orchestrator_core.api import SessionUpdateRequest
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_webapi.db.orchestrator import OrchestratorDB


def _make_record(
    session_id: str = "01JTEST0000000000000000001",
    vendor: str = "test_vendor",
    status: str = "running",
) -> SessionRecord:
    return SessionRecord(
        id=session_id,
        vendor=vendor,
        prompt="Test prompt",
        workdir="/tmp/work",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        status=status,  # type: ignore[arg-type]
    )


@pytest.fixture
def db(tmp_path):
    db = OrchestratorDB(tmp_path / "sessions.db")
    db.connect()
    yield db
    db.close()


def test_save_and_get(db):
    record = _make_record()
    db.save_session(record)

    fetched = db.get_session(record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.vendor == "test_vendor"
    assert fetched.prompt == "Test prompt"
    assert fetched.status == "running"
    assert fetched.ended_at is None


def test_get_missing_returns_none(db):
    result = db.get_session("nonexistent-id")
    assert result is None


def test_update_status(db):
    record = _make_record()
    db.save_session(record)

    ended = datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)
    db.update_session_status(
        record.id,
        SessionUpdateRequest(status="completed", ended_at=ended, vendor_session_id="vs-123"),
    )

    fetched = db.get_session(record.id)
    assert fetched is not None
    assert fetched.status == "completed"
    assert fetched.ended_at == ended
    assert fetched.vendor_session_id == "vs-123"


def test_list_sessions_all(db):
    r1 = _make_record("01JTEST0000000000000000001", vendor="claude", status="running")
    r2 = _make_record("01JTEST0000000000000000002", vendor="openai", status="completed")
    db.save_session(r1)
    db.save_session(r2)

    sessions = db.list_sessions()
    assert len(sessions) == 2


def test_list_sessions_filtered_by_vendor(db):
    r1 = _make_record("01JTEST0000000000000000001", vendor="claude", status="running")
    r2 = _make_record("01JTEST0000000000000000002", vendor="openai", status="completed")
    db.save_session(r1)
    db.save_session(r2)

    sessions = db.list_sessions(vendor="claude")
    assert len(sessions) == 1
    assert sessions[0].vendor == "claude"


def test_list_sessions_filtered_by_status(db):
    r1 = _make_record("01JTEST0000000000000000001", vendor="v1", status="running")
    r2 = _make_record("01JTEST0000000000000000002", vendor="v2", status="completed")
    r3 = _make_record("01JTEST0000000000000000003", vendor="v3", status="failed")
    db.save_session(r1)
    db.save_session(r2)
    db.save_session(r3)

    running = db.list_sessions(status="running")
    assert len(running) == 1
    assert running[0].id == r1.id


def test_context_manager(tmp_path):
    with OrchestratorDB(tmp_path / "ctx.db") as db:
        record = _make_record()
        db.save_session(record)
        fetched = db.get_session(record.id)
    assert fetched is not None
    assert fetched.id == record.id


def test_update_status_preserves_vendor_session_id(db):
    """vendor_session_id set in first update must not be cleared by second update."""
    record = _make_record()
    db.save_session(record)
    db.update_session_status(record.id, SessionUpdateRequest(status="running", vendor_session_id="vs-abc"))
    # second update without vendor_session_id should keep existing value
    db.update_session_status(
        record.id,
        SessionUpdateRequest(status="completed", ended_at=datetime(2024, 1, 2, tzinfo=UTC)),
    )

    fetched = db.get_session(record.id)
    assert fetched is not None
    assert fetched.vendor_session_id == "vs-abc"
