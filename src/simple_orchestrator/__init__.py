from .db import OrchestratorDB, SessionHistoryDB
from .settings import AgentSettings, OrchestratorSettings, setup_logging
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
from .vendors import BaseVendor, ClaudeCodeVendor, GithubCopilotVendor, OpenCodeVendor

__all__ = [
    "OrchestratorDB",
    "OrchestratorSettings",
    "AgentSettings",
    "setup_logging",
    "SessionHistoryDB",
    "AgentConfig",
    "AgentRecord",
    "McpConfig",
    "McpHttpConfig",
    "McpSseConfig",
    "McpStdioConfig",
    "ModelInfo",
    "QueueItem",
    "PollingRunner",
    "QueueRunner",
    "SessionConfig",
    "SessionRecord",
    "SkillConfig",
    "BaseVendor",
    "ClaudeCodeVendor",
    "GithubCopilotVendor",
    "OpenCodeVendor",
]


def main() -> None:
    import argparse
    import asyncio

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

    args = parser.parse_args()

    if args.command == "mcp-server":
        from .mcp_server import serve
        serve()

    elif args.command == "start":
        asyncio.run(_start())

    else:
        parser.print_help()


async def _start() -> None:
    import asyncio
    import logging

    from .db.orchestrator import OrchestratorDB
    from .mcp_server import serve_sse_async
    from .polling_runner import PollingRunner
    from .queue_runner import QueueRunner
    from .settings import OrchestratorSettings, setup_logging
    from .vendors.claude_code import ClaudeCodeVendor

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
