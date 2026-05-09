"""
Centralized logging configuration for Simple Orchestrator services.

Provides per-service logger factories with consistent formatting and configuration.
In DEBUG mode, logs include caller file location (filename:lineno).
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class _CallerInfoFilter(logging.Filter):
    """Add caller file and line number information to log records in DEBUG mode."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.DEBUG:
            record.caller_info = ""
            return True

        frame = inspect.currentframe()
        if frame is None:
            record.caller_info = ""
            return True

        caller_frame = frame
        for _ in range(8):
            if caller_frame.f_back is None:
                break
            caller_frame = caller_frame.f_back
            filename = caller_frame.f_code.co_filename
            if "logging" not in filename and "__init__.py" not in filename:
                break

        record.caller_info = f"{Path(caller_frame.f_code.co_filename).name}:{caller_frame.f_lineno}"
        return True


def _build_formatter(log_level: LogLevel) -> logging.Formatter:
    if log_level == "DEBUG":
        return logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)-35s [%(caller_info)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _has_rotating_file_handler(logger: logging.Logger, *, path: Path) -> bool:
    resolved = str(path.resolve())
    return any(isinstance(h, TimedRotatingFileHandler) and h.baseFilename == resolved for h in logger.handlers)


def _has_console_handler(logger: logging.Logger) -> bool:
    return any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, TimedRotatingFileHandler) for h in logger.handlers
    )


@dataclass(frozen=True)
class ServiceLoggerFactory:
    service: str
    internal_log_filename: str = "orchestrator.log"
    vendor_log_filename: str = "vendor.log"

    @property
    def _internal_root(self) -> str:
        return f"simple_orchestrator.{self.service}.internal"

    @property
    def _vendor_root(self) -> str:
        return f"simple_orchestrator.{self.service}.vendor"

    def setup(
        self,
        logs_dir: Path,
        log_level: LogLevel = "INFO",
        *,
        enable_console: bool = True,
        configure_root: bool = False,
    ) -> None:
        """
        Configure internal and vendor loggers for this service.

        If configure_root=True, attach the internal file handler to the root logger to capture
        third-party logs (e.g. uvicorn) into the same file without changing logger call sites.
        """
        level = logging.getLevelName(log_level)
        logs_dir.mkdir(parents=True, exist_ok=True)

        formatter = _build_formatter(log_level)
        caller_filter = _CallerInfoFilter()

        internal_file = logs_dir / self.internal_log_filename
        internal_logger = logging.getLogger(self._internal_root)
        internal_logger.setLevel(level)
        internal_logger.propagate = False

        if not _has_rotating_file_handler(internal_logger, path=internal_file):
            internal_handler = TimedRotatingFileHandler(
                internal_file,
                when="midnight",
                backupCount=7,
                encoding="utf-8",
            )
            internal_handler.setLevel(level)
            internal_handler.setFormatter(formatter)
            internal_handler.addFilter(caller_filter)
            internal_logger.addHandler(internal_handler)

        vendor_file = logs_dir / self.vendor_log_filename
        vendor_logger = logging.getLogger(self._vendor_root)
        vendor_logger.setLevel(level)
        vendor_logger.propagate = False

        if not _has_rotating_file_handler(vendor_logger, path=vendor_file):
            vendor_handler = TimedRotatingFileHandler(
                vendor_file,
                when="midnight",
                backupCount=7,
                encoding="utf-8",
            )
            vendor_handler.setLevel(level)
            vendor_handler.setFormatter(formatter)
            vendor_handler.addFilter(caller_filter)
            vendor_logger.addHandler(vendor_handler)

        if enable_console and not _has_console_handler(internal_logger):
            console = logging.StreamHandler()
            console.setLevel(level)
            console.setFormatter(formatter)
            console.addFilter(caller_filter)
            internal_logger.addHandler(console)
            vendor_logger.addHandler(console)

        if configure_root:
            root = logging.getLogger()
            root.setLevel(level)
            if not _has_rotating_file_handler(root, path=internal_file):
                root_handler = TimedRotatingFileHandler(
                    internal_file,
                    when="midnight",
                    backupCount=7,
                    encoding="utf-8",
                )
                root_handler.setLevel(level)
                root_handler.setFormatter(formatter)
                root_handler.addFilter(caller_filter)
                root.addHandler(root_handler)

    def internal(self, name: str) -> logging.Logger:
        return logging.getLogger(f"{self._internal_root}.{name}")

    def vendor(self, name: str) -> logging.Logger:
        return logging.getLogger(f"{self._vendor_root}.{name}")


def get_logger_factory(service: str) -> ServiceLoggerFactory:
    return ServiceLoggerFactory(service=service)
