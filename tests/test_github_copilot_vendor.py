"""Tests for GithubCopilotVendor — model passthrough and full session flow."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from simple_orchestrator_core.models.model import ModelInfo
from simple_orchestrator_core.models.session import SessionConfig, SessionRecord
from simple_orchestrator_worker.vendors.github_copilot import GithubCopilotVendor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_store():
    class _Store:
        def __init__(self) -> None:
            self.records: dict[str, SessionRecord] = {}

        async def save(self, record: SessionRecord) -> None:
            self.records[record.id] = record

        async def update_status(
            self,
            session_id: str,
            status: str,
            *,
            ended_at: datetime | None = None,
            vendor_session_id: str | None = None,
        ) -> None:
            rec = self.records.get(session_id)
            if rec is None:
                return
            rec.status = status
            if ended_at is not None:
                rec.ended_at = ended_at
            if vendor_session_id is not None:
                rec.vendor_session_id = vendor_session_id

    return _Store()


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


def test_default_model(session_store):
    vendor = GithubCopilotVendor(MagicMock(), model="gpt-4o")
    assert vendor._model == "gpt-4o"


def test_custom_model(session_store):
    vendor = GithubCopilotVendor(MagicMock(), model="gpt-4.1")
    assert vendor._model == "gpt-4.1"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


def test_list_models_returns_github_copilot_vendor(session_store):
    session = _make_copilot_session()
    raw_model = MagicMock()
    raw_model.id = "gpt-4.1"
    raw_model.name = "GPT-4.1"
    client = _make_copilot_client(session, models=[raw_model])

    vendor = GithubCopilotVendor(session_store, model="gpt-4.1")

    with patch("simple_orchestrator_worker.vendors.github_copilot.CopilotClient", return_value=client):
        models = asyncio.run(vendor.list_models())

    assert len(models) == 1
    assert models[0] == ModelInfo(id="gpt-4.1", name="GPT-4.1", vendor="github_copilot")


# ---------------------------------------------------------------------------
# Model passthrough — the key GPT-4.1 test
# ---------------------------------------------------------------------------


def test_execute_session_passes_gpt41_model(session_store):
    """SessionConfig.model='gpt-4.1' must reach create_session(model=...)."""
    copilot_session = _make_copilot_session()
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(session_store, model="gpt-4o")  # default is 4o
    config = SessionConfig(prompt="hello", model="gpt-4.1")

    async def run():
        with patch("simple_orchestrator_worker.vendors.github_copilot.CopilotClient", return_value=client):
            stream = await vendor.execute_session(config)
            return [e async for e in stream]

    events = asyncio.run(run())

    client.create_session.assert_awaited_once()
    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1", f"Expected gpt-4.1, got {kwargs['model']}"

    # First event must confirm session was created
    assert events[0]["type"] == "session_created"
    assert events[0]["session_id"] == copilot_session.session_id


def test_execute_session_falls_back_to_instance_model(session_store):
    """When SessionConfig.model is None, instance default model is used."""
    copilot_session = _make_copilot_session()
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(session_store, model="gpt-4.1")
    config = SessionConfig(prompt="hello", model=None)

    async def run():
        with patch("simple_orchestrator_worker.vendors.github_copilot.CopilotClient", return_value=client):
            stream = await vendor.execute_session(config)
            async for _ in stream:
                pass

    asyncio.run(run())

    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1"


def test_run_session_passes_gpt41_model(session_store):
    """_run_session (background path) also passes model='gpt-4.1' to create_session."""
    copilot_session = _make_copilot_session()
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(session_store, model="gpt-4o")
    config = SessionConfig(prompt="do something", model="gpt-4.1")

    with patch("simple_orchestrator_worker.vendors.github_copilot.CopilotClient", return_value=client):
        asyncio.run(vendor._run_session("test-session-id", config))

    client.create_session.assert_awaited_once()
    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1"


# ---------------------------------------------------------------------------
# Full run_sync() flow with gpt-4.1
# ---------------------------------------------------------------------------


def test_full_run_sync_flow_with_gpt41(session_store):
    """
    Full flow: run() -> _run_session() -> copilot session created with gpt-4.1
    -> DB record updated -> returns completed status.
    """
    import anyio

    copilot_session = _make_copilot_session("copilot-session-xyz")
    client = _make_copilot_client(copilot_session)

    vendor = GithubCopilotVendor(session_store, model="gpt-4o")
    config = SessionConfig(prompt="write tests", model="gpt-4.1", workdir="/tmp/test")

    with patch("simple_orchestrator_worker.vendors.github_copilot.CopilotClient", return_value=client):
        session_id, final_status = anyio.run(vendor.run, config)

    assert final_status == "completed"

    record = session_store.records.get(session_id)
    assert record is not None
    assert record.vendor == "github_copilot"
    assert record.status == "completed"

    # Verify model was passed correctly
    client.create_session.assert_awaited_once()
    _, kwargs = client.create_session.call_args
    assert kwargs["model"] == "gpt-4.1"

    # Verify prompt was sent (send_and_wait blocks until idle)
    copilot_session.send_and_wait.assert_awaited_once_with("write tests")


# ---------------------------------------------------------------------------
# Kill flow
# ---------------------------------------------------------------------------


def test_vendor_kill_calls_abort(session_store):
    """kill_sync() / _vendor_kill() must call session.abort() on active handle."""
    copilot_session = _make_copilot_session()

    vendor = GithubCopilotVendor(session_store, model="gpt-4.1")

    # Manually insert handle to simulate mid-run state
    vendor._active_handles["fake-session"] = copilot_session

    asyncio.run(vendor._vendor_kill("fake-session"))

    copilot_session.abort.assert_awaited_once()
    assert "fake-session" not in vendor._active_handles


def test_vendor_kill_noop_when_no_handle(session_store):
    """_vendor_kill on unknown session_id must not raise."""
    vendor = GithubCopilotVendor(session_store, model="gpt-4.1")
    asyncio.run(vendor._vendor_kill("nonexistent-session"))  # should not raise
