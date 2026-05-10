"""Integration tests for the distributed architecture using the HTTP client.

The worker and TUI must not access the DB directly; they use the OrchestratorApiClient
which talks to the FastAPI Web API over HTTP (using ASGITransport in tests).
"""

from __future__ import annotations

import pytest
from mock_agent import MockAgent
from simple_orchestrator_core.api import (
    AgentUpsertRequest,
    EnqueueRequest,
)
from simple_orchestrator_core.settings import WorkerSettings
from simple_orchestrator_worker.session_store import ApiSessionStore
from simple_orchestrator_worker.worker_runner import WorkerRunner


@pytest.mark.anyio
async def test_api_enqueue_and_worker_execution_success(orch_db, distributed_client):
    await distributed_client.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )

    item = await distributed_client.enqueue(
        EnqueueRequest(agent_id="mock-test-agent", prompt="Please analyze this test code and provide feedback"),
    )
    assert item.status == "pending"

    store = ApiSessionStore(distributed_client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=False, delay_seconds=0.0)
    runner = WorkerRunner(
        client=distributed_client,
        vendors={"mock": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=1.0),
    )

    lease = await distributed_client.dequeue_next()
    assert lease is not None
    await runner._process_lease(lease)

    completed = await distributed_client.get_queue_item(item.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.started_at is not None
    assert completed.ended_at is not None
    assert completed.session_id is not None

    # Verify directly in DB for extra certainty
    db_item = orch_db.get_queue_item(item.id)
    assert db_item is not None
    assert db_item.status == "completed"

    assert vendor.executed_sessions
    assert vendor.executed_sessions[0][1].startswith("Please analyze")

    session = await distributed_client.get_session(completed.session_id)
    assert session is not None
    assert session.vendor == "mock"
    assert session.status == "completed"


@pytest.mark.anyio
async def test_api_enqueue_and_worker_execution_failure(orch_db, distributed_client):
    await distributed_client.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )

    item = await distributed_client.enqueue(EnqueueRequest(agent_id="mock-test-agent", prompt="This prompt will fail"))

    store = ApiSessionStore(distributed_client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=True, delay_seconds=0.0)
    runner = WorkerRunner(
        client=distributed_client,
        vendors={"mock": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=1.0),
    )

    lease = await distributed_client.dequeue_next()
    assert lease is not None
    await runner._process_lease(lease)

    failed = await distributed_client.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"

    # Verify directly in DB
    db_item = orch_db.get_queue_item(item.id)
    assert db_item is not None
    assert db_item.status == "failed"
