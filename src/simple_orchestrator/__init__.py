import argparse
import asyncio
import logging

from .db import OrchestratorDB, SessionHistoryDB
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
from .settings import AgentSettings, OrchestratorSettings, setup_logging
from .tui import run_tui
from .vendors import BaseVendor, ClaudeCodeVendor, GithubCopilotVendor, OpenCodeVendor

__all__ = [
    "AgentConfig",
    "AgentRecord",
    "AgentSettings",
    "BaseVendor",
    "ClaudeCodeVendor",
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
    "run_tui",
    "setup_logging",
]


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-orchestrator")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "start",
        help="Start queue runner + MCP server (SSE on configured host:port)",
    )
    subparsers.add_parser(
        "mcp-server",
        help="Start MCP server on stdio only (used when spawned as MCP subprocess)",
    )
    subparsers.add_parser(
        "tui",
        help="Open the terminal dashboard to monitor the queue",
    )

    args = parser.parse_args()

    if args.command == "mcp-server":
        serve()

    elif args.command == "start":
        asyncio.run(_start())

    elif args.command == "tui":
        asyncio.run(run_tui())

    else:
        parser.print_help()


async def _start() -> None:
    settings = OrchestratorSettings()
    setup_logging(settings)

    async with OrchestratorDB(settings.db_path) as db:
        vendors: dict = {"claude_code": ClaudeCodeVendor(db)}
        runner = QueueRunner(db, vendors, settings)
        poller = PollingRunner(db, settings.pollings)

        log = logging.getLogger(__name__)
        log.info(
            "Starting orchestrator — MCP SSE at http://%s:%d/sse",
            settings.mcp_server_host,
            settings.mcp_server_port,
        )

        await asyncio.gather(
            runner.run_forever(),
            poller.run_forever(),
            serve_sse_async(settings.mcp_server_host, settings.mcp_server_port),
        )
