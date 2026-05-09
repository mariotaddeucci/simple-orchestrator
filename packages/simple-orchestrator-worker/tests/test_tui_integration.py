"""Integration tests for the new architecture without binding a real HTTP port.

The worker must not access the DB directly; it uses a client interface that, in production,
talks to the Web API over HTTP. In tests we use an in-process adapter that calls the Web API DB.
"""

from __future__ import annotations

import pytest
from mock_agent import MockAgent
from simple_orchestrator_core.api import (
    AgentUpsertRequest,
    QueueDequeueResponse,
    QueueUpdateRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
)
from simple_orchestrator_core.session_config_builder import build_session_config
from simple_orchestrator_core.settings import WebApiSettings, WorkerSettings
from simple_orchestrator_webapi.db.orchestrator import OrchestratorDB
from simple_orchestrator_worker.session_store import ApiSessionStore
from simple_orchestrator_worker.worker_runner import WorkerRunner


@pytest.fixture
def orch_db(tmp_path):
    db = OrchestratorDB(tmp_path / "tui_test.db")
    db.connect()
    yield db
    db.close()


@pytest.fixture
def webapi_settings(tmp_path):
    return WebApiSettings(
        db_path=str(tmp_path / "tui_test.db"),
        logs_dir=tmp_path / "logs",
        log_level="INFO",
    )


class InProcessApiClient:
    """Test-only adapter that implements the subset of OrchestratorApiClient used by the worker/vendors."""

    def __init__(self, *, db: OrchestratorDB, settings: WebApiSettings) -> None:
        self._db = db
        self._settings = settings

    async def dequeue_next(self) -> QueueDequeueResponse | None:
        item = self._db.dequeue_next()
        if not item:
            return None
        agent = self._db.get_agent(item.agent_id)
        assert agent is not None
        global_mcps = self._db.list_mcps(is_global=True, enabled=True)
        session_config = build_session_config(agent=agent, item=item, global_mcps=global_mcps)
        return QueueDequeueResponse(
            item=item,
            vendor=agent.vendor,
            timeout_minutes=agent.task_timeout_minutes,
            session_config=session_config,
        )

    async def update_queue_item(self, item_id: str, req: QueueUpdateRequest):  # type: ignore[no-untyped-def]
        return self._db.update_queue_item_api(item_id, req)

    async def create_session(self, req: SessionCreateRequest) -> None:
        self._db.save_session(req.record)

    async def update_session(self, session_id: str, req: SessionUpdateRequest) -> None:
        self._db.update_session_status(session_id, req)


@pytest.mark.anyio
async def test_tui_like_enqueue_and_worker_execution_success(orch_db, webapi_settings, tmp_path):
    orch_db.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            workdir=str(tmp_path / "workdir"),
            model="mock-model-1",
        ),
    )

    item = orch_db.enqueue(agent_id="mock-test-agent", prompt="Please analyze this test code and provide feedback")
    assert item.status == "pending"

    client = InProcessApiClient(db=orch_db, settings=webapi_settings)
    store = ApiSessionStore(client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=False, delay_seconds=0.0)
    runner = WorkerRunner(
        client=client,
        vendors={"mock": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=1.0),
    )

    lease = await client.dequeue_next()
    assert lease is not None
    await runner._process_lease(lease)

    completed = orch_db.get_queue_item(item.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.started_at is not None
    assert completed.ended_at is not None
    assert completed.session_id is not None

    assert vendor.executed_sessions
    assert vendor.executed_sessions[0][1].startswith("Please analyze")

    session = orch_db.get_session(completed.session_id)
    assert session is not None
    assert session.vendor == "mock"
    assert session.status == "completed"


@pytest.mark.anyio
async def test_tui_like_enqueue_and_worker_execution_failure(orch_db, webapi_settings, tmp_path):
    orch_db.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            workdir=str(tmp_path / "workdir"),
            model="mock-model-1",
        ),
    )

    item = orch_db.enqueue(agent_id="mock-test-agent", prompt="This prompt will fail")
    client = InProcessApiClient(db=orch_db, settings=webapi_settings)
    store = ApiSessionStore(client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=True, delay_seconds=0.0)
    runner = WorkerRunner(
        client=client,
        vendors={"mock": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=1.0),
    )

    lease = await client.dequeue_next()
    assert lease is not None
    await runner._process_lease(lease)

    failed = orch_db.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"
