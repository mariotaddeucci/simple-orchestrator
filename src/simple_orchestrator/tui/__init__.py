"""TUI submodule — launch with run_tui()."""

from __future__ import annotations

from simple_orchestrator.cron_runner import CronRunner
from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.logging_config import get_internal_logger, setup_logging
from simple_orchestrator.polling_runner import PollingRunner
from simple_orchestrator.queue_runner import QueueRunner
from simple_orchestrator.settings import OrchestratorSettings
from simple_orchestrator.tui.app import OrchestratorTUI
from simple_orchestrator.vendors import ClaudeCodeVendor, GithubCopilotVendor, OpenCodeVendor

__all__ = ["OrchestratorTUI", "run_tui"]


def run_tui() -> None:
    settings = OrchestratorSettings()
    setup_logging(settings.logs_dir, settings.log_level, enable_console=False)
    log_file = settings.logs_dir / "orchestrator.log"

    log = get_internal_logger(__name__)
    log.info("Starting TUI")

    with OrchestratorDB(settings.db_path) as db:
        vendors: dict = {
            "claude_code": ClaudeCodeVendor(db),
            "github_copilot": GithubCopilotVendor(db),
            "opencode": OpenCodeVendor(db),
        }
        runner = QueueRunner(db, vendors, settings)
        poller = PollingRunner(db, settings.pollings)
        cron_runner = CronRunner(db, settings)

        app = OrchestratorTUI(db, log_file, settings, vendors, runner, poller, cron_runner)
        app.run()

    log.info("TUI stopped")
