"""Integration tests for the standalone architecture without binding a real HTTP port."""

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
async def test_standalone_enqueue_and_worker_execution_success(orch_db, standalone_client):
    await standalone_client.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )

    item = await standalone_client.enqueue(
        EnqueueRequest(agent_id="mock-test-agent", prompt="Please analyze this test code and provide feedback"),
    )
    assert item.status == "pending"

    store = ApiSessionStore(standalone_client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=False, delay_seconds=0.0)
    runner = WorkerRunner(
        client=standalone_client,
        vendors={"mock": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=1.0),
    )

    lease = await standalone_client.dequeue_next()
    assert lease is not None
    await runner._process_lease(lease)

    completed = await standalone_client.get_queue_item(item.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.started_at is not None
    assert completed.ended_at is not None
    assert completed.session_id is not None

    assert vendor.executed_sessions
    assert vendor.executed_sessions[0][1].startswith("Please analyze")

    session = await standalone_client.get_session(completed.session_id)
    assert session is not None
    assert session.vendor == "mock"
    assert session.status == "completed"


@pytest.mark.anyio
async def test_standalone_enqueue_and_worker_execution_failure(orch_db, standalone_client):
    await standalone_client.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )

    item = await standalone_client.enqueue(
        EnqueueRequest(agent_id="mock-test-agent", prompt="This prompt will fail"),
    )
    store = ApiSessionStore(standalone_client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=True, delay_seconds=0.0)
    runner = WorkerRunner(
        client=standalone_client,
        vendors={"mock": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=1.0),
    )

    lease = await standalone_client.dequeue_next()
    assert lease is not None
    await runner._process_lease(lease)

    failed = await standalone_client.get_queue_item(item.id)
    assert failed is not None
    assert failed.status == "failed"
