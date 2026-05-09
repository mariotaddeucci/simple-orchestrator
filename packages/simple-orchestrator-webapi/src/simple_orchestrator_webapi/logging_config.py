from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal


def setup_logging(logs_dir: Path, log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "orchestrator.log"

    root = logging.getLogger()
    root.setLevel(log_level)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)-35s %(message)s")

    handler = TimedRotatingFileHandler(log_file, when="midnight", backupCount=7, encoding="utf-8")
    handler.setFormatter(fmt)
    root.handlers = [handler]


def get_internal_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"simple_orchestrator_webapi.{name}")
