"""
Centralized logging configuration for Simple Orchestrator.

Provides two separate log streams:
1. Internal logs: orchestrator operations (queue, cron, polling, DB)
2. Vendor logs: vendor session execution and agent interactions

In DEBUG mode, logs include file location (filename:lineno) for better tracing.
"""

import inspect
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal

# Logger names for different subsystems
INTERNAL_LOGGER = "simple_orchestrator.internal"
VENDOR_LOGGER = "simple_orchestrator.vendor"


class CallerInfoFilter(logging.Filter):
    """Add caller file and line number information to log records in DEBUG mode."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Add simplified caller info for DEBUG level
        if record.levelno == logging.DEBUG:
            # Get the actual caller frame (skip logging framework frames)
            frame = inspect.currentframe()
            if frame:
                # Walk up the stack to find the actual caller
                # Skip: filter -> log method -> actual caller
                caller_frame = frame
                for _ in range(8):  # Walk up max 8 frames
                    if caller_frame.f_back:
                        caller_frame = caller_frame.f_back
                        filename = caller_frame.f_code.co_filename
                        # Stop when we find a frame outside the logging module
                        if "logging" not in filename and "__init__.py" not in filename:
                            break

                filename = Path(caller_frame.f_code.co_filename).name
                lineno = caller_frame.f_lineno
                record.caller_info = f"{filename}:{lineno}"
        else:
            record.caller_info = ""

        return True


def setup_logging(
    logs_dir: Path,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
    *,
    enable_console: bool = True,
) -> None:
    """
    Configure dual logging streams: internal (orchestrator) and vendor (agents/sessions).

    Internal logs: queue operations, cron, polling, database operations
    Vendor logs: vendor session execution, agent interactions

    Args:
        logs_dir: Directory for log files
        log_level: Minimum log level to record
        enable_console: If True, also output logs to console (disable for TUI)
    """
    level = logging.getLevelName(log_level)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # DEBUG format includes caller file:line for tracing
    # INFO+ format uses the standard format
    if log_level == "DEBUG":
        fmt = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)-35s [%(caller_info)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        fmt = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    caller_filter = CallerInfoFilter()

    # Configure internal logger (orchestrator operations)
    internal_logger = logging.getLogger(INTERNAL_LOGGER)
    internal_logger.setLevel(level)
    internal_logger.propagate = False

    # File handler for internal logs
    internal_file = logs_dir / "orchestrator.log"
    if not any(
        isinstance(h, TimedRotatingFileHandler) and h.baseFilename == str(internal_file.resolve())
        for h in internal_logger.handlers
    ):
        fh_internal = TimedRotatingFileHandler(
            internal_file,
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        fh_internal.setLevel(level)
        fh_internal.setFormatter(fmt)
        fh_internal.addFilter(caller_filter)
        internal_logger.addHandler(fh_internal)

    # Configure vendor logger (vendor/agent execution)
    vendor_logger = logging.getLogger(VENDOR_LOGGER)
    vendor_logger.setLevel(level)
    vendor_logger.propagate = False

    # File handler for vendor logs
    vendor_file = logs_dir / "vendor.log"
    if not any(
        isinstance(h, TimedRotatingFileHandler) and h.baseFilename == str(vendor_file.resolve())
        for h in vendor_logger.handlers
    ):
        fh_vendor = TimedRotatingFileHandler(
            vendor_file,
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        fh_vendor.setLevel(level)
        fh_vendor.setFormatter(fmt)
        fh_vendor.addFilter(caller_filter)
        vendor_logger.addHandler(fh_vendor)

    # Optional console handler (shared for both loggers)
    if enable_console and not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, TimedRotatingFileHandler)
        for h in internal_logger.handlers
    ):
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(fmt)
        sh.addFilter(caller_filter)
        internal_logger.addHandler(sh)
        vendor_logger.addHandler(sh)


def get_internal_logger(name: str) -> logging.Logger:
    """
    Get a logger for internal orchestrator operations.

    Use for: queue operations, cron, polling, database, settings, etc.
    Logs to: logs/orchestrator.log

    Args:
        name: Usually __name__ of the calling module

    Returns:
        Logger instance for internal operations
    """
    return logging.getLogger(f"{INTERNAL_LOGGER}.{name}")


def get_vendor_logger(name: str) -> logging.Logger:
    """
    Get a logger for vendor/agent operations.

    Use for: vendor session execution, agent interactions, vendor-specific operations
    Logs to: logs/vendor.log

    Args:
        name: Usually __name__ of the calling module

    Returns:
        Logger instance for vendor operations
    """
    return logging.getLogger(f"{VENDOR_LOGGER}.{name}")
