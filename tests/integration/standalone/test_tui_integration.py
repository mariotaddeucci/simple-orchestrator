"""Integration tests for the new architecture without binding a real HTTP port.

The worker must not access the DB directly; it uses a client interface that, in production,
talks to the Web API over HTTP. In tests we use an in-process adapter that calls the Web API DB.
"""

from __future__ import annotations

import pytest
from mock_agent import MockAgent
from simple_orchestrator_core.api import (
    AgentUpsertRequest,
)
from simple_orchestrator_core.settings import WorkerSettings
from simple_orchestrator_database import OrchestratorDB
from simple_orchestrator_worker.session_store import ApiSessionStore
from simple_orchestrator_worker.worker_runner import WorkerRunner
from utils import InProcessOrchestratorClient


@pytest.fixture
def orch_db(tmp_path):
    db = OrchestratorDB(tmp_path / "tui_test.db")
    db.connect()
    yield db
    db.close()


@pytest.mark.anyio
async def test_tui_like_enqueue_and_worker_execution_success(orch_db):
    orch_db.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )

    item = orch_db.enqueue(agent_id="mock-test-agent", prompt="Please analyze this test code and provide feedback")
    assert item.status == "pending"

    client = InProcessOrchestratorClient(db=orch_db)
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
async def test_tui_like_enqueue_and_worker_execution_failure(orch_db):
    orch_db.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )

    item = orch_db.enqueue(agent_id="mock-test-agent", prompt="This prompt will fail")
    client = InProcessOrchestratorClient(db=orch_db)
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
