from __future__ import annotations

import anyio
import pytest
from simple_orchestrator_core.settings import WorkerSettings
from simple_orchestrator_worker.worker_runner import WorkerRunner
from ulid import ULID


class _FakeClient:
    def __init__(self, stop_event: anyio.Event) -> None:
        self.calls: int = 0
        self._stop_event = stop_event

    async def send_heartbeat(self, _hb) -> None:
        self.calls += 1
        self._stop_event.set()


@pytest.mark.anyio
async def test_worker_sends_heartbeat_until_stopped() -> None:
    stop_event = anyio.Event()
    client = _FakeClient(stop_event)
    settings = WorkerSettings(
        api_url="http://test",
        api_key="test-key",
        worker_id=str(ULID()),
        heartbeat_interval_seconds=999,
    )

    runner = WorkerRunner(client=client, vendors={}, settings=settings)  # type: ignore[arg-type]
    runner._stop_event = stop_event  # pragma: no cover
    await runner._heartbeat_loop()
    assert client.calls == 1
