from __future__ import annotations

from simple_orchestrator_core.settings import WorkerSettings

from simple_orchestrator_worker.logging_config import get_internal_logger, setup_logging
from simple_orchestrator_worker.worker_service import run_worker_forever


def main() -> None:
    settings = WorkerSettings()

    # Ensure required directories exist
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.git_cache_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(settings.logs_dir, settings.log_level)

    log = get_internal_logger(__name__)
    log.info("Starting worker — polling %s", settings.api_url)

    import anyio  # noqa: PLC0415

    anyio.run(run_worker_forever, settings)
