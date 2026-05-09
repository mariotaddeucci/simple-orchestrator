from __future__ import annotations

from typing import Any

import httpx


class OrchestratorApiClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            r = await client.get("/health")
            r.raise_for_status()
            return r.json()

    async def list_agents(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=20.0) as client:
            r = await client.get("/agents")
            r.raise_for_status()
            return r.json()["agents"]

    async def list_queue(self, *, status: str | None = None, agent_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if agent_id is not None:
            params["agent_id"] = agent_id
        async with httpx.AsyncClient(base_url=self._base_url, timeout=20.0) as client:
            r = await client.get("/queue", params=params)
            r.raise_for_status()
            return r.json()["items"]

    async def enqueue(
        self,
        *,
        agent_id: str,
        prompt: str,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"agent_id": agent_id, "prompt": prompt}
        if workdir is not None:
            payload["workdir"] = workdir
        async with httpx.AsyncClient(base_url=self._base_url, timeout=20.0) as client:
            r = await client.post("/queue", json=payload)
            r.raise_for_status()
            return r.json()["item"]

    async def cancel(self, item_id: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=20.0) as client:
            r = await client.post(f"/queue/{item_id}/cancel")
            r.raise_for_status()

    async def kill(self, item_id: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=20.0) as client:
            r = await client.post(f"/queue/{item_id}/kill")
            r.raise_for_status()
