from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from types import ModuleType

app = typer.Typer(help="Simple Orchestrator CLI", no_args_is_help=True)


def _import_or_exit(module: str, *, extra: str) -> ModuleType:
    try:
        return __import__(module, fromlist=["_unused"])
    except ImportError as e:  # pragma: no cover
        _print_missing_dep(extra=extra, err=e)
        raise typer.Exit(1) from e


def _print_missing_dep(*, extra: str, err: ImportError) -> None:
    sys.stderr.write(f"Missing dependency for this command: {err}\n")
    sys.stderr.write(f'Install with: uv add "simple-orchestrator[{extra}]"\n')
    sys.stderr.write(f'Or with pip: pip install "simple-orchestrator[{extra}]"\n')


@app.command("webapi")
def cmd_webapi() -> None:
    """Start the Web API server (serves REST and owns the SQLite DB)."""
    webapi_cli = _import_or_exit("simple_orchestrator_webapi.webapi_cli", extra="webapi")
    webapi_cli.main()


@app.command("worker")
def cmd_worker() -> None:
    """Start a background worker (connects to the Web API via HTTP)."""
    worker_cli = _import_or_exit("simple_orchestrator_worker.worker_cli", extra="worker")
    worker_cli.main()


@app.command("tui")
def cmd_tui(
    distributed: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--distributed", help="Connect to a running WebAPI instead of using the DB directly"),
    ] = False,
) -> None:
    """Start the TUI. Standalone by default (direct DB); --distributed uses a running WebAPI."""
    from simple_orchestrator_core.settings import TuiSettings  # noqa: PLC0415

    settings = TuiSettings()
    standalone = settings.standalone and not distributed

    if standalone:
        _run_standalone_tui(settings)
    else:
        _run_distributed_tui(settings)


def _run_distributed_tui(settings: object) -> None:
    """TUI backed by OrchestratorApiClient (HTTP → webapi → DB)."""
    try:
        from simple_orchestrator_api_client import OrchestratorApiClient  # noqa: PLC0415
        from simple_orchestrator_tui.app import OrchestratorTUI  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        _print_missing_dep(extra="tui", err=e)
        raise typer.Exit(1) from e

    from simple_orchestrator_core.settings import TuiSettings  # noqa: PLC0415

    s = settings if isinstance(settings, TuiSettings) else TuiSettings()
    OrchestratorTUI(
        client=OrchestratorApiClient(s.api_url, api_key=s.api_key),
    ).run()


def _run_standalone_tui(settings: object) -> None:
    """TUI + embedded worker, both backed directly by OrchestratorDB (no HTTP)."""
    try:
        from simple_orchestrator_core.settings import TuiSettings, WorkerSettings  # noqa: PLC0415
        from simple_orchestrator_database.repository import OrchestratorDB  # noqa: PLC0415
        from simple_orchestrator_tui.app import OrchestratorTUI  # noqa: PLC0415
        from simple_orchestrator_worker.worker_runner import WorkerRunner  # noqa: PLC0415
        from simple_orchestrator_worker.worker_service import build_vendors  # noqa: PLC0415

        from .standalone import StandaloneClient, StandaloneSessionStore  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        _print_missing_dep(extra="standalone", err=e)
        raise typer.Exit(1) from e

    s = settings if isinstance(settings, TuiSettings) else TuiSettings()
    worker_settings = WorkerSettings()

    db = OrchestratorDB(s.db_path)
    client = StandaloneClient(db)
    store = StandaloneSessionStore(db)
    vendors = build_vendors(session_store=store)
    runner = WorkerRunner(client=client, vendors=vendors, settings=worker_settings)

    OrchestratorTUI(client=client, background_worker=runner.start).run()


def main() -> None:
    app()
