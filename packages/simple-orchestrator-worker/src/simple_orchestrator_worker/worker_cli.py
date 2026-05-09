from __future__ import annotations

from simple_orchestrator_worker.logging_config import get_internal_logger, setup_logging
from simple_orchestrator_worker.settings import OrchestratorSettings


def main() -> None:
    settings = OrchestratorSettings()
    setup_logging(settings.logs_dir, settings.log_level)

    log = get_internal_logger(__name__)
    log.info("Starting worker — REST API at http://%s:%d", settings.api_host, settings.api_port)

    import uvicorn  # noqa: PLC0415

    uvicorn.run("simple_orchestrator_worker.api:app", host=settings.api_host, port=settings.api_port, log_level="info")
