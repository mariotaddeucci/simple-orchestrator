from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from simple_orchestrator_api_client import OrchestratorApiClient
from simple_orchestrator_core.api import EnqueueRequest
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.settings import TuiSettings
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    TabbedContent,
    TabPane,
    TextArea,
)


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

    def __init__(self, agents: list[AgentRecord]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        options = [(f"{a.name} ({a.id})", a.id) for a in self._agents]
        with Vertical():
            yield Label("Enqueue task", id="title")
            if options:
                yield Select(options, prompt="Select agent", id="agent_select")
            else:
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
        agent_id = self._get_agent_id()
        workdir_raw = self.query_one("#workdir", Input).value.strip()
        prompt = self.query_one("#prompt", TextArea).text.strip()
        if not agent_id or not prompt:
            return
        self.dismiss(_EnqueueResult(agent_id=agent_id, prompt=prompt, workdir=workdir_raw or None))

    def _get_agent_id(self) -> str:
        try:
            sel = self.query_one("#agent_select", Select)
            v = sel.value
            return str(v) if v and v is not Select.BLANK else ""
        except Exception:  # noqa: S110
            pass
        try:
            return self.query_one("#agent_id", Input).value.strip()
        except Exception:
            return ""


class OrchestratorTUI(App[None]):
    TITLE = "Simple Orchestrator"

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "enqueue", "Enqueue"),
    ]

    def __init__(self, api_url: str, *, api_key: str) -> None:
        super().__init__()
        self._client = OrchestratorApiClient(api_url, api_key=api_key)
        self._api_url = api_url
        self._agents: list[AgentRecord] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(f"API: {self._api_url}", id="api-url")
        with TabbedContent():
            with TabPane("Queue", id="tab-queue"):
                yield DataTable(id="queue")
            with TabPane("Agents", id="tab-agents"):
                yield DataTable(id="agents")
            with TabPane("Events", id="tab-events"):
                yield DataTable(id="events")
        yield Footer()

    def on_mount(self) -> None:
        queue_table = self.query_one("#queue", DataTable)
        queue_table.cursor_type = "row"
        queue_table.add_column("id")
        queue_table.add_column("agent_id")
        queue_table.add_column("status")
        queue_table.add_column("created_at")
        queue_table.add_column("started_at")
        queue_table.add_column("ended_at")

        agents_table = self.query_one("#agents", DataTable)
        agents_table.cursor_type = "row"
        agents_table.add_column("id")
        agents_table.add_column("name")
        agents_table.add_column("vendor")
        agents_table.add_column("model")
        agents_table.add_column("workdir")

        events_table = self.query_one("#events", DataTable)
        events_table.cursor_type = "row"
        events_table.add_column("id")
        events_table.add_column("name")
        events_table.add_column("agent_id")
        events_table.add_column("schedule")
        events_table.add_column("next_run")
        events_table.add_column("enabled")

        self.set_interval(2.0, self.action_refresh)
        self.action_refresh()

    def action_enqueue(self) -> None:
        async def handle(result: _EnqueueResult | None) -> None:
            if not result:
                return
            await self._enqueue_async(result)

        self.push_screen(EnqueueModal(self._agents), handle)

    def action_refresh(self) -> None:
        self._refresh_async()

    @work(exclusive=True)
    async def _refresh_async(self) -> None:
        await self._refresh_queue()
        await self._refresh_agents()
        await self._refresh_events()

    async def _refresh_queue(self) -> None:
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

    async def _refresh_agents(self) -> None:
        table = self.query_one("#agents", DataTable)
        try:
            self._agents = await self._client.list_agents()
        except Exception as e:
            table.clear()
            table.add_row("error", "", str(e), "", "")
            return
        table.clear()
        for a in self._agents:
            table.add_row(a.id, a.name, a.vendor, a.model or "", a.workdir or "")

    async def _refresh_events(self) -> None:
        table = self.query_one("#events", DataTable)
        try:
            events = await self._client.list_events()
        except Exception as e:
            table.clear()
            table.add_row("error", "", "", str(e), "", "")
            return
        table.clear()
        for ev in events:
            sched = f"every {ev.interval_minutes}m" if ev.schedule_type == "interval" else f"cron: {ev.cron_expression}"
            table.add_row(
                ev.id,
                ev.name,
                ev.agent_id,
                sched,
                _fmt_dt(ev.next_run),
                "yes" if ev.enabled else "no",
            )

    async def _enqueue_async(self, result: _EnqueueResult) -> None:
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
    if isinstance(raw, datetime):
        return raw.strftime("%Y-%m-%d %H:%M:%S")
    return str(raw)


def main() -> None:
    settings = TuiSettings()
    OrchestratorTUI(api_url=settings.api_url, api_key=settings.api_key).run()
