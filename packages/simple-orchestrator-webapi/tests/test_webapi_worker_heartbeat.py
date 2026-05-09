from __future__ import annotations

import anyio
import httpx
import pytest
from simple_orchestrator_api_client import OrchestratorApiClient
from simple_orchestrator_core.models.worker_heartbeat import WorkerHeartbeat
from simple_orchestrator_webapi.api import create_app
from ulid import ULID


@pytest.mark.anyio
async def test_heartbeat_roundtrip_shows_alive_workers_in_health(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_DB_PATH", str(tmp_path / "orchestrator.db"))
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "test-key")
    monkeypatch.setenv("ORCHESTRATOR_HEARTBEAT_TTL_SECONDS", "60")

    app = create_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        client = OrchestratorApiClient("http://test", api_key="test-key", transport=transport)

        w1 = WorkerHeartbeat(id=str(ULID()), name="worker-1")
        w2 = WorkerHeartbeat(id=str(ULID()), name="worker-2")

        await client.send_heartbeat(w1)
        await anyio.sleep(0.01)
        await client.send_heartbeat(w2)

        health = await client.health()
        ids = {w.id for w in health.workers}
        assert ids == {w1.id, w2.id}

        await anyio.sleep(0.01)
        await client.send_heartbeat(WorkerHeartbeat(id=w1.id, name="worker-1b"))

        health2 = await client.health()
        assert {w.id for w in health2.workers} == {w1.id, w2.id}

        by_id = {w.id: w for w in health2.workers}
        assert by_id[w1.id].name == "worker-1b"
        assert health2.workers[0].id == w1.id  # most recent heartbeat first
