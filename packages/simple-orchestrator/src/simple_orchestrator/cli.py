from __future__ import annotations

import argparse
import sys
from types import ModuleType


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-orchestrator")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("worker", help="Start the worker (queue runner + REST API)")
    subparsers.add_parser("start", help="Alias for 'worker'")
    subparsers.add_parser("tui", help="Start the TUI (REST API client)")
    subparsers.add_parser("mcp-server", help="Start MCP server on stdio only (used when spawned as MCP subprocess)")

    args = parser.parse_args()

    if args.command == "mcp-server":
        _run_mcp_server()
        return

    if args.command in (None, "worker", "start"):
        _run_worker()
        return

    if args.command == "tui":
        _run_tui()
        return

    parser.print_help()


def _import_or_exit(module: str, *, extra: str) -> ModuleType:
    try:
        return __import__(module, fromlist=["_unused"])
    except ImportError as e:  # pragma: no cover
        _print_missing_dep(extra=extra, err=e)
        raise SystemExit(1) from e


def _print_missing_dep(*, extra: str, err: ImportError) -> None:
    sys.stderr.write(f"Missing dependency for this command: {err}\n")
    sys.stderr.write(f'Install with: uv add "simple-orchestrator[{extra}]"\n')
    sys.stderr.write(f'Or with pip: pip install "simple-orchestrator[{extra}]"\n')


def _run_worker() -> None:
    worker_cli = _import_or_exit("simple_orchestrator_worker.worker_cli", extra="worker")
    worker_cli.main()


def _run_mcp_server() -> None:
    mcp_server = _import_or_exit("simple_orchestrator_worker.mcp_server", extra="worker")
    mcp_server.serve()


def _run_tui() -> None:
    tui = _import_or_exit("simple_orchestrator_tui", extra="tui")
    tui.main()
