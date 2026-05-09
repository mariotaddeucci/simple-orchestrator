from __future__ import annotations

import anyio
from simple_orchestrator_api_client import OrchestratorApiClient
from simple_orchestrator_core.settings import WorkerSettings

from .logging_config import get_internal_logger
from .session_store import ApiSessionStore
from .vendors import ClaudeCodeVendor, GithubCopilotVendor, OpenCodeVendor
from .worker_runner import WorkerRunner

logger = get_internal_logger(__name__)


def build_vendors(*, session_store: ApiSessionStore) -> dict[str, object]:
    return {
        "claude_code": ClaudeCodeVendor(session_store),
        "opencode": OpenCodeVendor(session_store),
        "github_copilot": GithubCopilotVendor(session_store),
    }


async def run_worker_forever(settings: WorkerSettings) -> None:
    client = OrchestratorApiClient(settings.api_url, api_key=settings.api_key)
    store = ApiSessionStore(client)
    vendors = build_vendors(session_store=store)
    runner = WorkerRunner(client=client, vendors=vendors, settings=settings)
    logger.info("Worker started api_url=%s max_active_sessions=%d", settings.api_url, settings.max_active_sessions)
    await runner.start()


def run(settings: WorkerSettings | None = None) -> None:
    anyio.run(run_worker_forever, settings or WorkerSettings())
