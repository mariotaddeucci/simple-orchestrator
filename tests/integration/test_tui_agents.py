from __future__ import annotations

import pytest
from simple_orchestrator_tui.app import OrchestratorTUI
from textual.widgets import Button, DataTable, Input, TextArea
from utils import wait_until


@pytest.mark.anyio
async def test_tui_create_edit_delete_agent(orch_db, orchestrator_client) -> None:
    app = OrchestratorTUI(client=orchestrator_client, refresh_interval_seconds=0)
    async with app.run_test(size=(140, 50)) as pilot:
        agents_table = app.query_one("#agents", DataTable)

        await wait_until(pilot, lambda: agents_table.row_count == 0)

        # Create
        app.query_one("#agent_add", Button).press()
        await wait_until(pilot, lambda: app.screen.__class__.__name__ == "AgentEditorModal")

        agent_id = "test-agent-1"
        modal = app.screen
        modal.query_one("#id", Input).value = agent_id
        modal.query_one("#name", Input).value = "Test Agent"
        modal.query_one("#vendor", Input).value = "mock"
        modal.query_one("#model", Input).value = "mock-model-1"
        modal.query_one("#prompt", TextArea).text = "You are a test agent."

        modal.query_one("#save", Button).press()

        # Verify via DB
        await wait_until(pilot, lambda: orch_db.get_agent(agent_id) is not None)

        app.action_refresh()
        await wait_until(pilot, lambda: agents_table.row_count == 1)
        row = agents_table.get_row_at(0)
        assert str(row[0]) == agent_id
        assert str(row[1]) == "Test Agent"

        # Edit
        agents_table.move_cursor(row=0, column=0, animate=False)
        app.query_one("#agent_edit", Button).press()

        def _edit_modal_ready() -> bool:
            if app.screen.__class__.__name__ != "AgentEditorModal":
                return False
            try:
                return app.screen.query_one("#name", Input).value == "Test Agent"
            except Exception:
                return False

        await wait_until(pilot, _edit_modal_ready)

        modal = app.screen
        modal.query_one("#name", Input).value = "Edited Agent"
        modal.query_one("#save", Button).press()

        await wait_until(
            pilot,
            lambda: (a := orch_db.get_agent(agent_id)) is not None and a.name == "Edited Agent",
        )
        app.action_refresh()

        def _edited() -> bool:
            if agents_table.row_count != 1:
                return False
            r = agents_table.get_row_at(0)
            return str(r[1]) == "Edited Agent"

        await wait_until(pilot, _edited)

        # Delete
        agents_table.move_cursor(row=0, column=0, animate=False)
        app.query_one("#agent_delete", Button).press()
        await wait_until(pilot, lambda: app.screen.__class__.__name__ == "ConfirmModal")
        app.screen.query_one("#ok", Button).press()

        # Verify via DB
        await wait_until(pilot, lambda: orch_db.get_agent(agent_id) is None)

        await wait_until(pilot, lambda: agents_table.row_count == 0)
