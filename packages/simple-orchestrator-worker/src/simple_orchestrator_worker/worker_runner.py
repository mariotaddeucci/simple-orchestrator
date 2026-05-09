from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
from anyio import CapacityLimiter, create_task_group
from simple_orchestrator_api_client import OrchestratorApiClient
from simple_orchestrator_core.api import QueueDequeueResponse, QueueUpdateRequest
from simple_orchestrator_core.settings import WorkerSettings
from ulid import ULID

from .logging_config import get_internal_logger

logger = get_internal_logger(__name__)


@dataclass
class WorkerRunner:
    client: OrchestratorApiClient
    vendors: dict[str, object]
    settings: WorkerSettings = field(default_factory=WorkerSettings)

    _running: bool = field(default=False, init=False)
    _stop_event: anyio.Event | None = field(default=None, init=False)
    _workdir_locks: dict[str, anyio.abc.Lock] = field(default_factory=dict, init=False)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event = anyio.Event()

        limiter = CapacityLimiter(self.settings.max_active_sessions)

        async with create_task_group() as tg:
            while self._stop_event and not self._stop_event.is_set():
                lease = await self.client.dequeue_next()
                if lease is None:
                    with anyio.move_on_after(self.settings.poll_interval_seconds):
                        await self._stop_event.wait()
                    continue

                tg.start_soon(self._run_lease, lease, limiter)

    def stop(self) -> None:
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()

    async def _run_lease(self, lease: QueueDequeueResponse, limiter: CapacityLimiter) -> None:
        session_config = lease.session_config
        workdir = session_config.workdir or lease.item.workdir or lease.item.id

        async with limiter:
            lock = self._workdir_locks.get(workdir)
            if lock is None:
                lock = anyio.Lock()
                self._workdir_locks[workdir] = lock
            async with lock:
                await self._process_lease(lease)

    async def _process_lease(self, lease: QueueDequeueResponse) -> None:
        vendor = self.vendors.get(lease.vendor)
        if vendor is None:
            logger.error("queue %s: vendor %r not registered", lease.item.id, lease.vendor)
            await self.client.update_queue_item(
                lease.item.id,
                QueueUpdateRequest(status="failed", ended_at=datetime.now(UTC)),
            )
            return

        session_id = str(ULID())
        await self.client.update_queue_item(lease.item.id, QueueUpdateRequest(session_id=session_id))

        effective_timeout = lease.timeout_minutes or self.settings.default_task_timeout_minutes
        try:
            session_id, final_status = await vendor.run(  # type: ignore[attr-defined]
                lease.session_config,
                timeout_minutes=effective_timeout,
                session_id=session_id,
            )
            await self.client.update_queue_item(
                lease.item.id,
                QueueUpdateRequest(status=final_status, session_id=session_id, ended_at=datetime.now(UTC)),
            )
            logger.info("queue %s -> %s", lease.item.id, final_status)
        except Exception:
            logger.exception("queue %s raised an error", lease.item.id)
            await self.client.update_queue_item(
                lease.item.id,
                QueueUpdateRequest(status="failed", ended_at=datetime.now(UTC)),
            )
