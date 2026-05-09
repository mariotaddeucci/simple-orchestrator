from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from simple_orchestrator_core.models.worker_heartbeat import HealthResponse, WorkerHeartbeat, WorkerHeartbeatStatus
from ulid import ULID


def test_worker_heartbeat_accepts_ulid_and_default_type() -> None:
    worker_id = str(ULID())
    hb = WorkerHeartbeat(id=worker_id, name="worker-1")
    assert hb.id == worker_id
    assert hb.type == "agent-worker"
    assert hb.name == "worker-1"


def test_worker_heartbeat_rejects_invalid_ulid() -> None:
    with pytest.raises(ValidationError):
        WorkerHeartbeat(id="not-a-ulid")


def test_health_response_includes_workers() -> None:
    now = datetime.now(UTC)
    status = WorkerHeartbeatStatus(id=str(ULID()), type="agent-worker", name=None, last_heartbeat_at=now)
    resp = HealthResponse(workers=[status])
    assert resp.status == "ok"
    assert resp.workers[0].last_heartbeat_at == now
