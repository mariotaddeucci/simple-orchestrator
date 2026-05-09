from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from simple_orchestrator_core.logging import get_logger_factory

_FACTORY = get_logger_factory("worker")


def setup_logging(
    logs_dir: Path,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
    *,
    enable_console: bool = True,
) -> None:
    _FACTORY.setup(logs_dir, log_level, enable_console=enable_console)


def get_internal_logger(name: str) -> logging.Logger:
    return _FACTORY.internal(name)


def get_vendor_logger(name: str) -> logging.Logger:
    return _FACTORY.vendor(name)
