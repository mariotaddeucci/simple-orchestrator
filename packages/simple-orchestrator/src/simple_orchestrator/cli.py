from __future__ import annotations

import sys
from typing import TYPE_CHECKING

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


@app.command("standalone")
def cmd_standalone() -> None:
    """Start TUI with an embedded worker — both read/write the SQLite DB directly (no HTTP)."""
    from simple_orchestrator_core.settings import TuiSettings, WorkerSettings  # noqa: PLC0415

    try:
        from simple_orchestrator_database.repository import OrchestratorDB  # noqa: PLC0415
        from simple_orchestrator_tui.app import OrchestratorTUI  # noqa: PLC0415
        from simple_orchestrator_worker.worker_runner import WorkerRunner  # noqa: PLC0415
        from simple_orchestrator_worker.worker_service import build_vendors  # noqa: PLC0415

        from .standalone import StandaloneClient, StandaloneSessionStore  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        _print_missing_dep(extra="standalone", err=e)
        raise typer.Exit(1) from e

    tui_settings = TuiSettings()
    worker_settings = WorkerSettings()

    db = OrchestratorDB(tui_settings.db_path)
    client = StandaloneClient(db)
    store = StandaloneSessionStore(db)
    vendors = build_vendors(session_store=store)
    runner = WorkerRunner(client=client, vendors=vendors, settings=worker_settings)

    OrchestratorTUI(client=client, background_worker=runner.start).run()


@app.command("webapi")
def cmd_webapi() -> None:
    """Start the Web API server (owns the SQLite DB; required for distributed mode)."""
    webapi_cli = _import_or_exit("simple_orchestrator_webapi.webapi_cli", extra="webapi")
    webapi_cli.main()


@app.command("worker")
def cmd_worker() -> None:
    """Start a worker process (connects to a running webapi via HTTP)."""
    worker_cli = _import_or_exit("simple_orchestrator_worker.worker_cli", extra="worker")
    worker_cli.main()


@app.command("tui")
def cmd_tui() -> None:
    """Start the TUI only (connects to a running webapi via HTTP)."""
    from simple_orchestrator_core.settings import TuiSettings  # noqa: PLC0415

    try:
        from simple_orchestrator_api_client import OrchestratorApiClient  # noqa: PLC0415
        from simple_orchestrator_tui.app import OrchestratorTUI  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        _print_missing_dep(extra="tui", err=e)
        raise typer.Exit(1) from e

    settings = TuiSettings()
    OrchestratorTUI(
        client=OrchestratorApiClient(settings.api_url, api_key=settings.api_key),
    ).run()


def main() -> None:
    app()
