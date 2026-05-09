from __future__ import annotations

import anyio
import pytest
from simple_orchestrator_core.api import AgentUpsertRequest
from simple_orchestrator_core.settings import WorkerSettings
from simple_orchestrator_database import OrchestratorDB
from simple_orchestrator_tui.app import OrchestratorTUI
from simple_orchestrator_worker.session_store import ApiSessionStore
from simple_orchestrator_worker.worker_runner import WorkerRunner
from textual.widgets import Button, DataTable, Input, Select, TextArea

from .mock_agent import MockAgent
from .utils import InProcessOrchestratorClient, wait_until


@pytest.mark.anyio
async def test_tui_enqueue_and_process_with_dummy_agent(tmp_path) -> None:
    db = OrchestratorDB(tmp_path / "tui_queue.db")
    db.connect()
    db.upsert_agent(
        AgentUpsertRequest(
            id="mock-test-agent",
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            model="mock-model-1",
        ),
    )
    client = InProcessOrchestratorClient(db)

    store = ApiSessionStore(client)  # type: ignore[arg-type]
    vendor = MockAgent(store, should_fail=False, delay_seconds=0.0)
    runner = WorkerRunner(
        client=client,
        vendors={"mock": vendor},
        settings=WorkerSettings(
            poll_interval_seconds=0.05,
            heartbeat_interval_seconds=3600.0,
            max_active_sessions=1,
            default_task_timeout_minutes=1.0,
        ),
    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(runner.start)

        app = OrchestratorTUI(client=client, refresh_interval_seconds=0)
        async with app.run_test(size=(140, 50)) as pilot:
            await wait_until(pilot, lambda: app.query_one("#agents", DataTable).row_count == 1)

            app.action_enqueue()
            await wait_until(pilot, lambda: app.screen.__class__.__name__ == "EnqueueModal")

            modal = app.screen
            await wait_until(
                pilot,
                lambda: len(modal.query("#agent_select")) > 0 or len(modal.query("#agent_id")) > 0,
            )
            try:
                sel = modal.query_one("#agent_select", Select)
                sel.value = "mock-test-agent"
            except Exception:
                modal.query_one("#agent_id", Input).value = "mock-test-agent"
            modal.query_one("#prompt", TextArea).text = "Please process this from the TUI integration test"

            modal.query_one("#enqueue", Button).press()

            done_table = app.query_one("#queue_done", DataTable)

            def _completed() -> bool:
                if done_table.row_count < 1:
                    return False
                row = done_table.get_row_at(0)
                return str(row[1]) == "mock-test-agent" and str(row[2]) == "completed"

            await wait_until(
                pilot,
                lambda: any(it.status == "completed" for it in db.list_queue()),
                timeout_seconds=5.0,
            )
            app.action_refresh()
            await wait_until(pilot, _completed, timeout_seconds=5.0)

        runner.stop()
        tg.cancel_scope.cancel()

    db.close()
