from __future__ import annotations

import httpx
import pytest
from simple_orchestrator_api_client import OrchestratorApiClient
from simple_orchestrator_core.models.worker_heartbeat import WorkerHeartbeat
from ulid import ULID


@pytest.mark.anyio
async def test_client_health_and_heartbeat_use_expected_routes_and_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "workers": []})

        if request.url.path == "/heartbeat":
            assert request.headers.get("X-API-Key") == "test-key"
            return httpx.Response(200, json={"status": "ok"})

        raise AssertionError(f"unexpected path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    client = OrchestratorApiClient("http://test", api_key="test-key", transport=transport)

    health = await client.health()
    assert health.status == "ok"
    assert health.workers == []

    await client.send_heartbeat(WorkerHeartbeat(id=str(ULID()), name="w"))
