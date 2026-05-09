"""Unit tests for the new worker architecture (polls Web API, no DB access)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_orchestrator_core.api import QueueDequeueResponse, QueueUpdateRequest
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.mcp import McpStdioConfig
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_core.settings import WebApiSettings, WorkerSettings
from simple_orchestrator_webapi.session_config_builder import build_session_config
from simple_orchestrator_worker.worker_runner import WorkerRunner
from ulid import ULID


def _queue_item(*, agent_id: str, prompt: str) -> QueueItem:
    return QueueItem(
        id=str(ULID()),
        agent_id=agent_id,
        prompt=prompt,
        status="running",
        created_at=datetime.now(UTC),
    )


def test_build_session_config_merges_mcp_and_skills_and_workdir():
    settings = WebApiSettings(
        mcp_servers={"global_tool": McpStdioConfig(type="stdio", command="global-cmd", args=[])},
        skills=["global-skill"],
    )
    agent = AgentRecord(
        id="agent-1",
        name="Agent 1",
        prompt="p",
        vendor="fake",
        model="m",
        workdir="/agent-dir",
        created_at=datetime.now(UTC),
        mcp_servers={"agent_tool": McpStdioConfig(type="stdio", command="agent-cmd", args=[])},
        skills=["agent-skill"],
    )
    item = _queue_item(agent_id=agent.id, prompt="task")
    item.workdir = "/task-dir"

    cfg = build_session_config(settings=settings, agent=agent, item=item)
    assert "global_tool" in cfg.mcp_servers
    assert "agent_tool" in cfg.mcp_servers
    assert "global-skill" in cfg.skills
    assert "agent-skill" in cfg.skills
    assert cfg.workdir == "/task-dir"


@pytest.mark.anyio
async def test_worker_marks_failed_when_vendor_missing():
    item = _queue_item(agent_id="agent-1", prompt="task")
    lease = QueueDequeueResponse(
        item=item,
        vendor="missing",
        timeout_minutes=None,
        session_config=SessionConfig(prompt="task"),
    )

    class FakeClient:
        def __init__(self) -> None:
            self.updates: list[QueueUpdateRequest] = []

        async def update_queue_item(self, item_id: str, req: QueueUpdateRequest):  # type: ignore[no-untyped-def]
            assert item_id == item.id
            self.updates.append(req)
            return item

    client = FakeClient()
    runner = WorkerRunner(client=client, vendors={}, settings=WorkerSettings(default_task_timeout_minutes=0.01))
    await runner._process_lease(lease)

    assert client.updates
    assert any(u.status == "failed" for u in client.updates)


@pytest.mark.anyio
async def test_worker_updates_session_id_then_final_status():
    item = _queue_item(agent_id="agent-1", prompt="task")
    lease = QueueDequeueResponse(
        item=item,
        vendor="fake",
        timeout_minutes=None,
        session_config=SessionConfig(prompt="task", workdir="/w"),
    )

    class FakeClient:
        def __init__(self) -> None:
            self.updates: list[QueueUpdateRequest] = []

        async def update_queue_item(self, item_id: str, req: QueueUpdateRequest):  # type: ignore[no-untyped-def]
            assert item_id == item.id
            self.updates.append(req)
            return item

    class FakeVendor:
        def __init__(self) -> None:
            self.runs: list[tuple[str, float, str]] = []

        async def run(self, config: SessionConfig, *, timeout_minutes: float, session_id: str):  # type: ignore[no-untyped-def]
            self.runs.append((config.prompt, timeout_minutes, session_id))
            return session_id, "completed"

    client = FakeClient()
    vendor = FakeVendor()
    runner = WorkerRunner(
        client=client,
        vendors={"fake": vendor},
        settings=WorkerSettings(default_task_timeout_minutes=12.0),
    )
    await runner._process_lease(lease)

    assert vendor.runs
    assert vendor.runs[0][0] == "task"
    assert vendor.runs[0][1] == 12.0

    assert len(client.updates) >= 2
    assert client.updates[0].session_id is not None
    assert client.updates[-1].status == "completed"
    assert client.updates[-1].ended_at is not None
