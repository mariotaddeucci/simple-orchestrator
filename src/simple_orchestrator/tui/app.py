"""OrchestratorTUI — controller that wires service, workers, and views."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label, TabbedContent, TabPane

from simple_orchestrator.models.agent_record import AgentRecord
from simple_orchestrator.tui.modals.command_palette import CommandPalette
from simple_orchestrator.tui.modals.prompt_modal import PromptModal
from simple_orchestrator.tui.service import OrchestratorService
from simple_orchestrator.tui.widgets.chat_panel import ChatPanel
from simple_orchestrator.tui.widgets.log_panel import LogPanel
from simple_orchestrator.tui.widgets.queue_table import QueueTable
from simple_orchestrator.tui.widgets.scheduled_event_card import ScheduledEventCard
from simple_orchestrator.tui.widgets.terminal_panel import TerminalPanel

if TYPE_CHECKING:
    from textual.binding import BindingType

    from simple_orchestrator.cron_runner import CronRunner
    from simple_orchestrator.db.orchestrator import OrchestratorDB
    from simple_orchestrator.polling_runner import PollingRunner
    from simple_orchestrator.queue_runner import QueueRunner
    from simple_orchestrator.settings import OrchestratorSettings
    from simple_orchestrator.vendors.base import BaseVendor

_REFRESH_INTERVAL = 2.0
_FINISHED_LIMIT = 20


class OrchestratorTUI(App[None]):
    TITLE = "Simple Orchestrator — Dashboard"
    CSS_PATH = "app.tcss"

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("ctrl+p", "command_palette", "Commands"),
    ]

    _pending_count: reactive[int] = reactive(0)
    _running_count: reactive[int] = reactive(0)
    _finished_count: reactive[int] = reactive(0)

    def __init__(
        self,
        db: OrchestratorDB,
        log_file: Path,
        settings: OrchestratorSettings,
        vendors: dict[str, BaseVendor],
        runner: QueueRunner | None = None,
        poller: PollingRunner | None = None,
        cron_runner: CronRunner | None = None,
    ) -> None:
        super().__init__()
        self.service = OrchestratorService(db, settings)
        self._log_file = log_file
        self._settings = settings
        self._vendors = vendors
        self._runner = runner
        self._poller = poller
        self._cron_runner = cron_runner

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(id="sidebar"), ScrollableContainer(id="sidebar-events"):
            yield Label("📆  SCHEDULED EVENTS", classes="section-label events")

        with Vertical(id="main-content"):
            with Horizontal(id="columns"):
                with Vertical(classes="col", id="col-pending"):
                    yield Label("⏳  PENDING", classes="section-label pending")
                    yield QueueTable("pending", id="pending-table", classes="pending")

                with Vertical(classes="col", id="col-running"):
                    yield Label("▶   RUNNING", classes="section-label running")
                    yield QueueTable("running", id="running-table", classes="running")

                with Vertical(classes="col", id="col-finished"):
                    yield Label(f"✔   RECENTLY FINISHED (last {_FINISHED_LIMIT})", classes="section-label finished")
                    yield QueueTable("finished", id="finished-table", classes="finished")

            with TabbedContent(id="bottom-tabs"):
                with TabPane("Chat", id="tab-chat"):
                    yield ChatPanel(self._settings, self._vendors, id="chat-panel")
                with TabPane("Logs", id="tab-logs"):
                    yield LogPanel(self._log_file, id="log-panel")
                with TabPane("Terminal", id="tab-terminal"):
                    yield TerminalPanel(id="terminal-panel")

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh_all)
        self._refresh_all()
        self._start_queue_worker()
        self._start_cron_worker()
        self._start_polling_worker()
        self._start_mcp_server()

    def on_unmount(self) -> None:
        if self._runner:
            self._runner.stop()
        if self._cron_runner:
            self._cron_runner.stop()
        if self._poller:
            self._poller.stop()

    # ── workers ───────────────────────────────────────────────────────────────

    @work(name="queue-runner", exclusive=True)
    async def _start_queue_worker(self) -> None:
        if self._runner:
            await self._runner.start()

    @work(name="cron-runner", exclusive=True)
    async def _start_cron_worker(self) -> None:
        if self._cron_runner:
            await self._cron_runner.start()

    @work(name="polling-runner", exclusive=True)
    async def _start_polling_worker(self) -> None:
        if self._poller:
            await self._poller.start()

    @work(name="mcp-server", exclusive=True)
    async def _start_mcp_server(self) -> None:
        from simple_orchestrator.mcp_server import serve_sse_async  # noqa: PLC0415

        await serve_sse_async(self._settings.mcp_server_host, self._settings.mcp_server_port)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._refresh_all()

    def action_command_palette(self) -> None:
        async def handle(command_id: str | None) -> None:
            if command_id == "delegate-task":
                self._open_delegate_modal()
            elif command_id == "refresh":
                self._refresh_all()
            elif command_id == "queue-stats":
                stats = self.service.queue_stats()
                self.notify(
                    f"Pending: {stats['pending']} | Running: {stats['running']} | "
                    f"Completed: {stats['completed']} | Failed: {stats['failed']}",
                    title="Queue Statistics",
                    timeout=5,
                )

        self.push_screen(CommandPalette(), handle)

    # ── enqueue ───────────────────────────────────────────────────────────────

    def do_enqueue(self, agent: AgentRecord, prompt: str, workdir: str | None = None) -> None:
        self.service.enqueue(agent.id, prompt, workdir)
        agent_name = agent.nickname or agent.name
        self.notify(f"✓ Task enqueued for {agent_name}", title="Task Added", severity="information", timeout=3)
        self._refresh_all()

    def _open_delegate_modal(self) -> None:
        agents = self.service.list_agents()

        async def handle(result: tuple[str, str | None, str | None] | None) -> None:
            if not result:
                return
            prompt, workdir, agent_id = result
            if not agent_id:
                self.notify("Please select an agent", severity="warning")
                return
            agent = next((a for a in agents if a.id == agent_id), None)
            if not agent:
                self.notify("Agent not found", severity="error")
                return
            self.do_enqueue(agent, prompt, workdir)

        self.push_screen(PromptModal(None, agents), handle)

    # ── table actions (cell click) ────────────────────────────────────────────

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        table = event.data_table
        if not isinstance(table, QueueTable):
            return
        if table._col_keys.get("action") != event.coordinate.column:
            return
        item_id = str(event.coordinate.row)
        item = next((i for i in table._items if i.id == item_id), None)
        if not item:
            return
        if table._mode == "pending":
            self.service.cancel(item_id)
            self._refresh_all()
        elif table._mode == "running":
            self.service.kill(item)
            self._refresh_all()

    # ── fetch model: refresh all views ────────────────────────────────────────

    def _refresh_all(self) -> None:
        pending = self.service.list_pending()
        running = self.service.list_running()
        finished = self.service.list_finished()
        agents = self.service.list_agents()
        agent_labels = {a.id: a.nickname or a.name for a in agents}
        events = self.service.list_scheduled_events()

        self.query_one("#pending-table", QueueTable).refresh_rows(pending, agent_labels)
        self.query_one("#running-table", QueueTable).refresh_rows(running, agent_labels)
        self.query_one("#finished-table", QueueTable).refresh_rows(finished, agent_labels)

        self.query_one(".section-label.pending", Label).update(f"⏳  PENDING  [{len(pending)}]")
        self.query_one(".section-label.running", Label).update(f"▶   RUNNING  [{len(running)}]")
        self.query_one(".section-label.finished", Label).update(f"✔   RECENTLY FINISHED  [{len(finished)}]")
        self.query_one(".section-label.events", Label).update(f"📆  SCHEDULED EVENTS  [{len(events)}]")

        self._refresh_sidebar_events(events)
        self.query_one(LogPanel).refresh_logs()

    def _refresh_sidebar_events(self, events: list) -> None:
        container = self.query_one("#sidebar-events", ScrollableContainer)
        children = list(container.children)
        for child in children[1:]:
            child.remove()
        for event in events:
            container.mount(ScheduledEventCard(event))
