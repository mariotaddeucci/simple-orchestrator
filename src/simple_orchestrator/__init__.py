import argparse

from .db import OrchestratorDB, SessionHistoryDB
from .logging_config import get_internal_logger, setup_logging
from .mcp_server import serve
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
from .queue_runner import QueueRunner
from .settings import AgentSettings, OrchestratorSettings
from .skills import get_skill_path, list_skill_names
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
    "QueueItem",
    "QueueRunner",
    "SessionConfig",
    "SessionHistoryDB",
    "SessionRecord",
    "SkillConfig",
    "get_skill_path",
    "list_skill_names",
    "setup_logging",
]


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-orchestrator")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "worker",
        help="Start the async worker (queue runner + REST API)",
    )
    subparsers.add_parser(
        "start",
        help="Alias for 'worker'",
    )
    subparsers.add_parser(
        "mcp-server",
        help="Start MCP server on stdio only (used when spawned as MCP subprocess)",
    )

    args = parser.parse_args()

    if args.command == "mcp-server":
        serve()

    elif args.command in (None, "worker", "start"):
        _start_worker()

    else:
        parser.print_help()


def _start_worker() -> None:
    settings = OrchestratorSettings()
    setup_logging(settings.logs_dir, settings.log_level)

    log = get_internal_logger(__name__)
    log.info("Starting worker — REST API at http://%s:%d", settings.api_host, settings.api_port)

    import uvicorn  # noqa: PLC0415

    uvicorn.run("simple_orchestrator.api:app", host=settings.api_host, port=settings.api_port, log_level="info")
