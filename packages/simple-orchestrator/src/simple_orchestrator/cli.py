from __future__ import annotations

import argparse
import sys
from types import ModuleType


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-orchestrator")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("webapi", help="Start the Web API (DB mediator)")
    subparsers.add_parser("worker", help="Start the worker (polls the Web API)")
    subparsers.add_parser("start", help="Alias for 'webapi'")
    subparsers.add_parser("tui", help="Start the TUI (REST API client)")

    args = parser.parse_args()

    if args.command in (None, "webapi", "start"):
        _run_webapi()
        return

    if args.command == "worker":
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


def _run_webapi() -> None:
    webapi_cli = _import_or_exit("simple_orchestrator_webapi.webapi_cli", extra="webapi")
    webapi_cli.main()


def _run_tui() -> None:
    tui = _import_or_exit("simple_orchestrator_tui", extra="tui")
    tui.main()
