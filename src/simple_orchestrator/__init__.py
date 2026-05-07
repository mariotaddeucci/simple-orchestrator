import argparse
import asyncio
import threading

import anyio

from .cron_runner import CronRunner
from .db import OrchestratorDB, SessionHistoryDB
from .logging_config import get_internal_logger, setup_logging
from .mcp_server import serve, serve_sse_async
from .models import (
    AgentConfig,
    AgentRecord,
    McpConfig,
    McpHttpConfig,
    McpSseConfig,
    McpStdioConfig,
    ModelInfo,
    QueueItem,
    SessionConfig,
    SessionRecord,
    SkillConfig,
)
from .polling_runner import PollingRunner
from .queue_runner import QueueRunner
from .settings import AgentSettings, OrchestratorSettings
from .skills import get_skill_path, list_skill_names
from .tui import run_tui
from .vendors import BaseVendor, ClaudeCodeVendor, GithubCopilotVendor, OpenCodeVendor

__all__ = [
    "AgentConfig",
    "AgentRecord",
    "AgentSettings",
    "BaseVendor",
    "ClaudeCodeVendor",
    "CronRunner",
    "GithubCopilotVendor",
    "McpConfig",
    "McpHttpConfig",
    "McpSseConfig",
    "McpStdioConfig",
    "ModelInfo",
    "OpenCodeVendor",
    "OrchestratorDB",
    "OrchestratorSettings",
    "PollingRunner",
    "QueueItem",
    "QueueRunner",
    "SessionConfig",
    "SessionHistoryDB",
    "SessionRecord",
    "SkillConfig",
    "get_skill_path",
    "list_skill_names",
    "run_tui",
    "setup_logging",
]


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-orchestrator")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "start",
        help="Start queue runner + MCP server (SSE on configured host:port) without TUI",
    )
    subparsers.add_parser(
        "mcp-server",
        help="Start MCP server on stdio only (used when spawned as MCP subprocess)",
    )
    subparsers.add_parser(
        "tui",
        help="Open the terminal dashboard with background processes",
    )

    args = parser.parse_args()

    if args.command == "mcp-server":
        serve()

    elif args.command == "start":
        _start()

    elif args.command == "tui":
        run_tui()

    else:
        # Default to TUI when no command is specified
        run_tui()


def _start() -> None:
    settings = OrchestratorSettings()
    setup_logging(settings.logs_dir, settings.log_level)

    with OrchestratorDB(settings.db_path) as db:
        vendors: dict = {"claude_code": ClaudeCodeVendor(db)}
        runner = QueueRunner(db, vendors, settings)
        poller = PollingRunner(db, settings.pollings)

        log = get_internal_logger(__name__)
        log.info(
            "Starting orchestrator — MCP SSE at http://%s:%d/sse",
            settings.mcp_server_host,
            settings.mcp_server_port,
        )

        # Start runners in background threads with anyio.run() wrapper
        t1 = threading.Thread(target=lambda: anyio.run(runner.start), daemon=True)
        t2 = threading.Thread(target=lambda: anyio.run(poller.start), daemon=True)
        t1.start()
        t2.start()

        # MCP server (async) blocks main thread
        asyncio.run(serve_sse_async(settings.mcp_server_host, settings.mcp_server_port))
