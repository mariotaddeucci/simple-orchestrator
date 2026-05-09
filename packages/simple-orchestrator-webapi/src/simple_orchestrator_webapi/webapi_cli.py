from __future__ import annotations

from simple_orchestrator_core.settings import WebApiSettings

from .logging_config import get_internal_logger, setup_logging


def main() -> None:
    settings = WebApiSettings()
    setup_logging(settings.logs_dir, settings.log_level)

    log = get_internal_logger(__name__)
    log.info("Starting webapi at http://%s:%d", settings.webapi_host, settings.webapi_port)

    import uvicorn  # noqa: PLC0415

    uvicorn.run(
        "simple_orchestrator_webapi.api:app",
        host=settings.webapi_host,
        port=settings.webapi_port,
        log_level="info",
    )
