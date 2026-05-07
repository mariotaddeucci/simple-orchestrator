"""Tests for GithubCopilotVendor — model passthrough and full session flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.models.model import ModelInfo
from simple_orchestrator.models.session import SessionConfig
from simple_orchestrator.vendors.github_copilot import GithubCopilotVendor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def history_db(tmp_path):
    db = SessionHistoryDB(tmp_path / "sessions.db")
    await db.connect()
    yield db
    await db.close()


def _make_copilot_session(session_id: str = "copilot-session-abc") -> MagicMock:
    """Build a minimal CopilotSession mock that satisfies async-with + send."""
    session = MagicMock()
    session.session_id = session_id
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.send = AsyncMock()
    session.send_and_wait = AsyncMock(return_value=None)
    session.abort = AsyncMock()
    # on() registers callbacks — call them immediately with a sentinel value
    session.on = MagicMock()
    return session


def _make_copilot_client(session: MagicMock, models: list | None = None) -> MagicMock:
    """Build a CopilotClient mock."""
    if models is None:
        m = MagicMock()
        m.id = "gpt-4.1"
        m.name = "GPT-4.1"
        models = [m]

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.create_session = AsyncMock(return_value=session)
    client.list_models = AsyncMock(return_value=models)
    return client


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_default_model(history_db):
    vendor = GithubCopilotVendor.__new__(GithubCopilotVendor)
    vendor.__init__ = GithubCopilotVendor.__init__
    # Default should be "gpt-4o"
    vendor = GithubCopilotVendor(MagicMock(), model="gpt-4o")
    assert vendor._model == "gpt-4o"


def test_custom_model(history_db):
    vendor = GithubCopilotVendor(MagicMock(), model="gpt-4.1")
    assert vendor._model == "gpt-4.1"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_returns_github_copilot_vendor(history_db):
    session = _make_copilot_session()
    raw_model = MagicMock()
    raw_model.id = "gpt-4.1"
    raw_model.name = "GPT-4.1"
    client = _make_copilot_client(session, models=[raw_model])

    vendor = GithubCopilotVendor(history_db, model="gpt-4.1")

    with patch("simple_orchestrator.vendors.github_copilot.CopilotClient", return_value=client):
        models = await vendor.list_models()

    assert len(models) == 1
    assert models[0] == ModelInfo(id="gpt-4.1", name="GPT-4.1", vendor="github_copilot")


# ---------------------------------------------------------------------------
# Model passthrough — the key GPT-4.1 test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_session_passes_gpt41_model(history_db):
    """SessionConfig.model='gpt-4.1' must reach create_session(model=...)."""
    copilot_session = _make_copilot_session()
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(history_db, model="gpt-4o")  # default is 4o
    config = SessionConfig(prompt="hello", model="gpt-4.1")

    with patch("simple_orchestrator.vendors.github_copilot.CopilotClient", return_value=client):
        stream = await vendor.execute_session(config)
        events = [e async for e in stream]

    client.create_session.assert_awaited_once()
    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1", f"Expected gpt-4.1, got {kwargs['model']}"

    # First event must confirm session was created
    assert events[0]["type"] == "session_created"
    assert events[0]["session_id"] == copilot_session.session_id


@pytest.mark.asyncio
async def test_execute_session_falls_back_to_instance_model(history_db):
    """When SessionConfig.model is None, instance default model is used."""
    copilot_session = _make_copilot_session()
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(history_db, model="gpt-4.1")
    config = SessionConfig(prompt="hello", model=None)

    with patch("simple_orchestrator.vendors.github_copilot.CopilotClient", return_value=client):
        stream = await vendor.execute_session(config)
        async for _ in stream:
            pass

    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1"


@pytest.mark.asyncio
async def test_run_session_passes_gpt41_model(history_db):
    """_run_session (background path) also passes model='gpt-4.1' to create_session."""
    copilot_session = _make_copilot_session()
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(history_db, model="gpt-4o")
    config = SessionConfig(prompt="do something", model="gpt-4.1")

    with patch("simple_orchestrator.vendors.github_copilot.CopilotClient", return_value=client):
        await vendor._run_session("test-session-id", config)

    client.create_session.assert_awaited_once()
    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1"


# ---------------------------------------------------------------------------
# Full run() flow with gpt-4.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_run_flow_with_gpt41(history_db):
    """
    Full flow: run() → _run_session() → copilot session created with gpt-4.1
    → DB record updated → wait() returns completed record.
    """
    copilot_session = _make_copilot_session("copilot-session-xyz")
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(history_db, model="gpt-4o")
    config = SessionConfig(prompt="write tests", model="gpt-4.1")

    with patch("simple_orchestrator.vendors.github_copilot.CopilotClient", return_value=client):
        session_id = await vendor.run(config)
        record = await vendor.wait(session_id)

    assert record.status == "completed"
    assert record.vendor == "github_copilot"

    # Verify model was passed correctly
    client.create_session.assert_awaited_once()
    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1"

    # Verify prompt was sent (send_and_wait blocks until idle)
    copilot_session.send_and_wait.assert_awaited_once_with("write tests")


# ---------------------------------------------------------------------------
# Kill flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vendor_kill_calls_abort(history_db):
    """kill() must call session.abort() on active handle."""
    copilot_session = _make_copilot_session()

    vendor = GithubCopilotVendor(history_db, model="gpt-4.1")

    # Manually insert handle to simulate mid-run state
    vendor._active_handles["fake-session"] = copilot_session

    await vendor._vendor_kill("fake-session")

    copilot_session.abort.assert_awaited_once()
    assert "fake-session" not in vendor._active_handles


@pytest.mark.asyncio
async def test_vendor_kill_noop_when_no_handle(history_db):
    """_vendor_kill on unknown session_id must not raise."""
    vendor = GithubCopilotVendor(history_db, model="gpt-4.1")
    await vendor._vendor_kill("nonexistent-session")  # should not raise
