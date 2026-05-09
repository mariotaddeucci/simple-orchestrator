from __future__ import annotations

from abc import ABC, abstractmethod

from .models.worker_heartbeat import WorkerHeartbeat


class BaseNodeWorker(ABC):
    @abstractmethod
    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        raise NotImplementedError
