from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from simple_orchestrator_api_client import OrchestratorApiClient
from simple_orchestrator_core.api import EnqueueRequest
from simple_orchestrator_core.settings import TuiSettings
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, TextArea


@dataclass(frozen=True)
class _EnqueueResult:
    agent_id: str
    prompt: str
    workdir: str | None


class EnqueueModal(ModalScreen[_EnqueueResult | None]):
    DEFAULT_CSS = """
    EnqueueModal {
        align: center middle;
    }
    EnqueueModal > Vertical {
        width: 90%;
        max-width: 120;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $panel;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Enqueue task (REST API)", id="title")
            yield Input(placeholder="agent_id", id="agent_id")
            yield Input(placeholder="workdir (optional)", id="workdir")
            yield TextArea("", id="prompt")
            with Horizontal():
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Enqueue", variant="primary", id="enqueue")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#enqueue")
    def _enqueue(self) -> None:
        agent_id = self.query_one("#agent_id", Input).value.strip()
        workdir_raw = self.query_one("#workdir", Input).value.strip()
        prompt = self.query_one("#prompt", TextArea).text.strip()
        if not agent_id or not prompt:
            return
        self.dismiss(_EnqueueResult(agent_id=agent_id, prompt=prompt, workdir=workdir_raw or None))


class OrchestratorTUI(App[None]):
    TITLE = "Simple Orchestrator — TUI (API client)"

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "enqueue", "Enqueue"),
    ]

    def __init__(self, api_url: str, *, api_key: str) -> None:
        super().__init__()
        self._client = OrchestratorApiClient(api_url, api_key=api_key)
        self._api_url = api_url

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(f"API: {self._api_url}", id="api-url")
        yield DataTable(id="queue")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue", DataTable)
        table.cursor_type = "row"
        table.add_column("id")
        table.add_column("agent_id")
        table.add_column("status")
        table.add_column("created_at")
        table.add_column("started_at")
        table.add_column("ended_at")
        self.set_interval(2.0, self.action_refresh)
        self.action_refresh()

    def action_enqueue(self) -> None:
        async def handle(result: _EnqueueResult | None) -> None:
            if not result:
                return
            await self._enqueue_async(result)

        self.push_screen(EnqueueModal(), handle)

    def action_refresh(self) -> None:
        self._refresh_async()

    @work(exclusive=True)
    async def _refresh_async(self) -> None:
        table = self.query_one("#queue", DataTable)
        try:
            items = await self._client.list_queue()
        except Exception as e:
            table.clear()
            table.add_row("error", "", "", str(e), "", "")
            return

        table.clear()
        for it in items:
            table.add_row(
                it.id,
                it.agent_id,
                it.status,
                _fmt_dt(it.created_at),
                _fmt_dt(it.started_at),
                _fmt_dt(it.ended_at),
            )

    async def _enqueue_async(self, result: _EnqueueResult) -> None:
        # TODO: allow selecting agent_id from /agents + validate locally before sending.
        await self._client.enqueue(
            EnqueueRequest(agent_id=result.agent_id, prompt=result.prompt, workdir=result.workdir),
        )
        self.action_refresh()


def _fmt_dt(raw: Any) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw
    return str(raw)


def main() -> None:
    settings = TuiSettings()
    OrchestratorTUI(api_url=settings.api_url, api_key=settings.api_key).run()
