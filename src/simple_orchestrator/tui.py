"""
Terminal User Interface for monitoring the Simple Orchestrator queue.

Displays three columns (auto-refreshed every 2 s):
  • Pending   — items waiting to run
  • Running   — items currently being executed
  • Finished  — the last N completed/failed/killed/cancelled items

A sidebar shows agents and scheduled events (polling and cron schedules).
A log panel at the bottom shows recent entries from the orchestrator log file.

Launch via:
    simple-orchestrator tui
    simple-orchestrator    # defaults to TUI

Background processes (QueueRunner, PollingRunner, CronRunner, MCP server) run
automatically when the TUI is started.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from croniter import croniter
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, RichLog, Static, TextArea

from .cron_runner import CronRunner
from .db.orchestrator import OrchestratorDB
from .mcp_server import serve_sse_async
from .models.agent_record import AgentRecord
from .polling_runner import PollingRunner
from .queue_runner import QueueRunner
from .settings import OrchestratorSettings, setup_logging
from .vendors import ClaudeCodeVendor

if TYPE_CHECKING:
    from pathlib import Path

    from textual.binding import BindingType
    from textual.widgets._data_table import ColumnKey

    from .models.queue_item import QueueItem

_REFRESH_INTERVAL = 2.0  # seconds
_FINISHED_LIMIT = 20  # how many recent finished items to display
_LOG_DISPLAY_LINES = 100  # max lines shown in the log panel

_STATUS_STYLE: dict[str, str] = {
    "pending": "yellow",
    "running": "cyan",
    "completed": "green",
    "failed": "red",
    "killed": "red",
    "cancelled": "dim",
}

_LOG_LEVEL_STYLE: dict[str, str] = {
    "DEBUG": "dim",
    "INFO": "white",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold red on dark_red",
}


def _tail_lines(path: Path, n: int) -> list[str]:
    """Return the last *n* lines of *path*, or [] if the file doesn't exist.

    Reads the file in reverse chunks to avoid loading the entire file into
    memory when only a small tail is needed.
    """
    if not path.exists():
        return []
    chunk_size = 8192
    lines: list[str] = []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        remaining = fh.tell()
        buf = b""
        while remaining > 0 and len(lines) <= n:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            fh.seek(remaining)
            buf = fh.read(read_size) + buf
            lines = buf.decode("utf-8", errors="replace").splitlines(keepends=True)
    return lines[-n:]


def _parse_log_line(line: str) -> tuple[str, str, str, str]:
    """Parse a log line into (timestamp, level, name, message).

    Expected format: ``YYYY-MM-DDTHH:MM:SS LEVEL    name   message``
    Returns raw strings; falls back to ("", "INFO", "", line) on parse failure.
    """
    parts = line.rstrip("\n").split(None, 3)
    if len(parts) == 4:
        return parts[0], parts[1].strip(), parts[2].strip(), parts[3]
    return "", "INFO", "", line.rstrip("\n")


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _elapsed(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "—"
    finish = end or datetime.now(UTC)
    delta = finish - start.replace(tzinfo=UTC) if start.tzinfo is None else finish - start
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _truncate(text: str, max_len: int = 60) -> str:
    text = text.replace("\n", " ").strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def _styled(text: str, status: str) -> str:
    style = _STATUS_STYLE.get(status, "")
    return f"[{style}]{text}[/]" if style else text


def _format_next_run(next_run: datetime) -> str:
    """Format next run time as relative time from now."""
    now = datetime.now(UTC)
    delta = next_run - now
    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        return "overdue"

    if total_seconds < 60:
        return f"in {total_seconds}s"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"in {minutes}m"

    hours = minutes // 60
    if hours < 24:
        return f"in {hours}h"

    days = hours // 24
    return f"in {days}d"


class ScheduledEventCard(Static):
    """A card displaying a scheduled event (polling or cron)."""

    DEFAULT_CSS = """
    ScheduledEventCard {
        height: auto;
        border: solid $accent-darken-1;
        background: $panel;
        padding: 1 2;
        margin: 1 0;
    }

    ScheduledEventCard .event-type {
        text-style: bold;
        color: $warning;
    }

    ScheduledEventCard .event-agent {
        color: $text;
    }

    ScheduledEventCard .event-next-run {
        color: $success;
        text-style: dim;
    }

    ScheduledEventCard .event-schedule {
        color: $text-muted;
        text-style: dim;
    }
    """

    def __init__(self, event_type: str, agent_id: str, schedule: str, next_run: datetime, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.event_type = event_type  # "polling" or "cron"
        self.agent_id = agent_id
        self.schedule = schedule
        self.next_run = next_run

    def compose(self) -> ComposeResult:
        type_icon = "⏱️" if self.event_type == "polling" else "📅"
        yield Label(f"{type_icon} {self.event_type.upper()}", classes="event-type")
        yield Label(f"Agent: {self.agent_id}", classes="event-agent")
        yield Label(f"Next: {_format_next_run(self.next_run)}", classes="event-next-run")
        yield Label(f"Schedule: {self.schedule}", classes="event-schedule")


class AgentCard(Static):
    """A clickable card representing an agent."""

    DEFAULT_CSS = """
    AgentCard {
        height: auto;
        border: solid $accent;
        background: $panel;
        padding: 1 2;
        margin: 1 0;
    }

    AgentCard:hover {
        border: solid $success;
        background: $surface;
    }

    AgentCard .agent-name {
        text-style: bold;
        color: $text;
    }

    AgentCard .agent-vendor {
        color: $text-muted;
        text-style: dim;
    }
    """

    def __init__(self, agent: AgentRecord, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.can_focus = True

    def compose(self) -> ComposeResult:
        name = self.agent.nickname or self.agent.name
        vendor = self.agent.vendor
        yield Label(name, classes="agent-name")
        yield Label(f"[{vendor}]", classes="agent-vendor")

    async def on_click(self) -> None:
        """Open prompt input modal when card is clicked."""
        log = logging.getLogger(__name__)
        log.info("AgentCard clicked for agent: %s", self.agent.id)

        async def handle_prompt(prompt: str | None) -> None:
            log.info("handle_prompt callback invoked with prompt: %s", prompt[:50] if prompt else None)
            if prompt and isinstance(self.app, OrchestratorTUI):
                log.info("Calling enqueue_prompt for agent %s", self.agent.id)
                await self.app.enqueue_prompt(self.agent, prompt)
                log.info("enqueue_prompt completed for agent %s", self.agent.id)

        await self.app.push_screen(PromptModal(self.agent), handle_prompt)


class PromptModal(ModalScreen[str | None]):
    """Modal screen for entering a prompt for an agent."""

    DEFAULT_CSS = """
    PromptModal {
        align: center middle;
    }

    #prompt-dialog {
        width: 80;
        height: 25;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }

    #prompt-dialog .dialog-title {
        text-style: bold;
        color: $text;
        text-align: center;
        margin-bottom: 1;
    }

    #prompt-input {
        height: 15;
        margin-bottom: 1;
    }

    #button-container {
        layout: horizontal;
        height: 3;
        align: center middle;
    }

    #button-container Button {
        margin: 0 1;
    }
    """

    def __init__(self, agent: AgentRecord) -> None:
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with Container(id="prompt-dialog"):
            name = self.agent.nickname or self.agent.name
            yield Label(f"Enter prompt for: {name}", classes="dialog-title")
            yield TextArea(id="prompt-input", language="markdown")
            with Horizontal(id="button-container"):
                yield Button("OK", variant="primary", id="ok-button")
                yield Button("Cancel", variant="default", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-button":
            text_area = self.query_one("#prompt-input", TextArea)
            prompt = text_area.text.strip()
            if prompt:
                self.dismiss(prompt)
        elif event.button.id == "cancel-button":
            self.dismiss(None)


class QueueTable(DataTable):
    """A DataTable that renders QueueItem rows for a specific status group."""

    # Column definitions: (column_id, header_label)
    _PENDING_COLS: ClassVar[list[tuple[str, str]]] = [
        ("id", "ID"),
        ("agent", "Agent"),
        ("prompt", "Prompt"),
        ("queued", "Queued At"),
        ("action", "Action"),
    ]

    _RUNNING_COLS: ClassVar[list[tuple[str, str]]] = [
        ("id", "ID"),
        ("agent", "Agent"),
        ("prompt", "Prompt"),
        ("started", "Started At"),
        ("elapsed", "Elapsed"),
        ("action", "Action"),
    ]

    _FINISHED_COLS: ClassVar[list[tuple[str, str]]] = [
        ("id", "ID"),
        ("agent", "Agent"),
        ("status", "Status"),
        ("prompt", "Prompt"),
        ("ended", "Ended At"),
        ("elapsed", "Elapsed"),
    ]

    def __init__(self, mode: str, **kwargs: Any) -> None:
        super().__init__(show_cursor=True, zebra_stripes=True, **kwargs)
        self._mode = mode  # "pending" | "running" | "finished"
        self._col_keys: dict[str, ColumnKey] = {}
        self._items: list[QueueItem] = []  # Store items for action handling

    def on_mount(self) -> None:
        cols = {"pending": self._PENDING_COLS, "running": self._RUNNING_COLS, "finished": self._FINISHED_COLS}[
            self._mode
        ]
        for col_id, label in cols:
            self._col_keys[col_id] = self.add_column(label, key=col_id)

    def refresh_rows(self, items: list[QueueItem], agent_labels: dict[str, str]) -> None:
        self.clear()
        self._items = items  # Store items for action handling
        if not items:
            return

        if self._mode == "pending":
            for item in items:
                agent = agent_labels.get(item.agent_id, item.agent_id)
                self.add_row(
                    _styled(item.id[-8:], item.status),
                    agent,
                    _truncate(item.prompt),
                    _fmt_dt(item.created_at),
                    "[red]✕ Cancel[/]",
                    key=item.id,
                )
        elif self._mode == "running":
            for item in items:
                agent = agent_labels.get(item.agent_id, item.agent_id)
                self.add_row(
                    _styled(item.id[-8:], item.status),
                    agent,
                    _truncate(item.prompt),
                    _fmt_dt(item.started_at),
                    _elapsed(item.started_at, None),
                    "[red]✕ Kill[/]",
                    key=item.id,
                )
        else:  # finished
            for item in items:
                agent = agent_labels.get(item.agent_id, item.agent_id)
                self.add_row(
                    item.id[-8:],
                    agent,
                    _styled(item.status.upper(), item.status),
                    _truncate(item.prompt),
                    _fmt_dt(item.ended_at),
                    _elapsed(item.started_at, item.ended_at),
                    key=item.id,
                )


class OrchestratorTUI(App[None]):
    """Textual TUI that displays the Simple Orchestrator queue."""

    TITLE = "Simple Orchestrator — Dashboard"
    CSS = """
    Screen {
        layout: horizontal;
    }

    /* ── Sidebar for agents and scheduled events ───────────── */
    #sidebar {
        width: 28;
        border-right: solid $accent;
        background: $panel;
    }

    #sidebar-agents {
        height: auto;
        max-height: 50%;
    }

    #sidebar-events {
        height: auto;
        max-height: 50%;
    }

    .section-label.agents {
        background: $primary;
        color: $text;
    }

    .section-label.events {
        background: $warning;
        color: $text;
    }

    /* ── Main content area ────────────────────────────────── */
    #main-content {
        width: 1fr;
        layout: vertical;
    }

    /* ── Three-column queue area ────────────────────────────── */
    #columns {
        height: 3fr;
    }

    .col {
        width: 1fr;
        layout: vertical;
        border-right: solid $panel;
    }

    .col:last-of-type {
        border-right: none;
    }

    /* ── Section label strip ────────────────────────────────── */
    .section-label {
        background: $accent;
        color: $text;
        padding: 0 1;
        text-style: bold;
        height: 1;
    }

    .section-label.running {
        background: $success;
    }

    .section-label.finished {
        background: $panel;
    }

    .section-label.logs {
        background: $warning;
        color: $text;
    }

    QueueTable {
        height: 1fr;
        border: none;
    }

    /* ── Log panel ──────────────────────────────────────────── */
    #log-panel {
        height: 2fr;
        border: none;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    _pending_count: reactive[int] = reactive(0)
    _running_count: reactive[int] = reactive(0)
    _finished_count: reactive[int] = reactive(0)

    def __init__(
        self,
        db: OrchestratorDB,
        log_file: Path,
        settings: OrchestratorSettings,
        runner: QueueRunner | None = None,
        poller: PollingRunner | None = None,
        cron_runner: CronRunner | None = None,
    ) -> None:
        super().__init__()
        self._db = db
        self._log_file = log_file
        self._settings = settings
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._agents: list[AgentRecord] = []  # Store agents for interaction
        self._runner = runner
        self._poller = poller
        self._cron_runner = cron_runner

    def compose(self) -> ComposeResult:
        yield Header()

        # Sidebar with agents and scheduled events
        with Vertical(id="sidebar"):
            yield Label("👥  AGENTS", classes="section-label agents")
            yield ScrollableContainer(id="sidebar-agents")
            yield Label("📆  SCHEDULED EVENTS", classes="section-label events")
            yield ScrollableContainer(id="sidebar-events")

        # Main content area
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

            yield Label("📋  LOGS", classes="section-label logs")
            yield RichLog(id="log-panel", highlight=False, markup=True, wrap=False, auto_scroll=True)

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._do_refresh)
        # Kick off an immediate refresh without blocking on_mount
        task = asyncio.create_task(self._load_data())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def action_refresh(self) -> None:
        await self._load_data()

    async def _do_refresh(self) -> None:
        await self._load_data()

    async def enqueue_prompt(self, agent: AgentRecord, prompt: str) -> None:
        """Enqueue a new task for the given agent with the provided prompt."""
        log = logging.getLogger(__name__)
        log.info("TUI enqueue_prompt: agent_id=%s, prompt=%s", agent.id, prompt[:50])
        item = await self._db.enqueue(agent_id=agent.id, prompt=prompt)
        log.info("TUI enqueue_prompt: item created with id=%s, status=%s", item.id, item.status)
        await self._load_data()
        log.info("TUI enqueue_prompt: data reloaded")

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle cell selection in queue tables to trigger kill/cancel actions."""
        table = event.data_table
        if not isinstance(table, QueueTable):
            return

        # Check if the action column was clicked
        col_key = event.coordinate.column
        if table._col_keys.get("action") != col_key:
            return

        # Get the row key (item ID)
        row_key = event.coordinate.row
        if row_key is None:
            return

        item_id = str(row_key)

        # Find the item
        item = next((i for i in table._items if i.id == item_id), None)
        if not item:
            return

        # Create a background task to handle the action
        if table._mode == "pending":
            task = asyncio.create_task(self._cancel_item(item_id))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        elif table._mode == "running":
            task = asyncio.create_task(self._kill_item(item))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

    async def _cancel_item(self, item_id: str) -> None:
        """Cancel a pending queue item."""
        await self._db.cancel_queue_item(item_id)
        await self._load_data()

    async def _kill_item(self, item: QueueItem) -> None:
        """Kill a running queue item by killing its session."""
        if not item.session_id:
            return
        # We need to get the vendor to kill the session
        # For now, we'll just update the status in DB
        # A more complete implementation would need access to the vendor
        await self._db.update_queue_item(
            item.id,
            status="killed",
            ended_at=datetime.now(UTC),
        )
        await self._load_data()

    def _refresh_log_panel(self) -> None:
        """Read the log file tail and repopulate the RichLog widget."""
        log_panel = self.query_one("#log-panel", RichLog)
        lines = _tail_lines(self._log_file, _LOG_DISPLAY_LINES)
        log_panel.clear()
        for line in lines:
            ts, level, name, message = _parse_log_line(line)
            style = _LOG_LEVEL_STYLE.get(level, "white")
            ts_part = f"[dim]{ts}[/dim] " if ts else ""
            level_part = f"[{style}]{level:<8}[/]"
            name_part = f"[dim cyan]{name}[/dim cyan] " if name else ""
            log_panel.write(f"{ts_part}{level_part} {name_part}{message}")

    async def _merge_agents(self) -> list[AgentRecord]:
        """Get agents from TOML settings only."""
        agents_map: dict[str, AgentRecord] = {}

        # Get agents from settings only
        for agent_id, agent_settings in self._settings.agents.items():
            agents_map[agent_id] = AgentRecord(
                id=agent_id,
                name=agent_settings.name,
                nickname=agent_settings.nickname,
                prompt=agent_settings.resolve_prompt(),
                model=agent_settings.model,
                vendor=agent_settings.vendor,
                workdir=agent_settings.workdir,
                created_at=datetime.now(UTC),  # TOML agents don't have a creation time
            )

        return list(agents_map.values())

    async def _load_data(self) -> None:
        pending = await self._db.list_queue(status="pending")
        running = await self._db.list_queue(status="running")

        # Finished = completed + failed + killed + cancelled, newest first
        all_items = await self._db.list_queue()
        finished = [i for i in all_items if i.status in ("completed", "failed", "killed", "cancelled") and i.ended_at]
        finished.sort(key=lambda i: i.ended_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        finished = finished[:_FINISHED_LIMIT]

        # Merge agents from settings and DB (settings take priority, matching QueueRunner behavior)
        all_agents = await self._merge_agents()
        self._agents = all_agents  # Store for later use
        agent_labels: dict[str, str] = {a.id: a.nickname or a.name for a in all_agents}

        # Update sidebar with agent cards
        sidebar_agents = self.query_one("#sidebar-agents", ScrollableContainer)
        sidebar_agents.remove_children()
        for agent in all_agents:
            sidebar_agents.mount(AgentCard(agent))

        # Update sidebar with scheduled events
        sidebar_events = self.query_one("#sidebar-events", ScrollableContainer)
        sidebar_events.remove_children()

        # Collect all scheduled events with their next run times
        scheduled_events: list[tuple[datetime, str, str, str]] = []  # (next_run, type, agent_id, schedule)

        # Add polling events
        for polling in self._settings.pollings:
            now = datetime.now(UTC)
            # Calculate next run based on interval
            # Use a key for tracking last run time (similar to cron)
            key = f"polling_{polling.agent_id}_{polling.prompt}"
            last_run = await self._db.get_cron_last_run(key)
            if last_run:
                # Calculate next run from last run + interval
                next_run = datetime.fromtimestamp(last_run.timestamp() + polling.interval_minutes * 60, UTC)
            else:
                # First run is immediate (already happened at startup), so next is now + interval
                next_run = datetime.now(UTC)

            schedule_str = f"every {polling.interval_minutes}m"
            scheduled_events.append((next_run, "polling", polling.agent_id, schedule_str))

        # Add cron events
        for cron_cfg in self._settings.crons:
            key = f"cron_{cron_cfg.agent_id}_{cron_cfg.prompt}"
            last_run = await self._db.get_cron_last_run(key)
            now = datetime.now(UTC)

            if last_run:
                ci = croniter(cron_cfg.cron, last_run.replace(tzinfo=None))
                next_run = ci.get_next(datetime).replace(tzinfo=UTC)
            else:
                # Never run before - next run is now or calculated from now
                ci = croniter(cron_cfg.cron, now.replace(tzinfo=None))
                next_run = ci.get_next(datetime).replace(tzinfo=UTC)

            scheduled_events.append((next_run, "cron", cron_cfg.agent_id, cron_cfg.cron))

        # Sort by next run time (soonest first)
        scheduled_events.sort(key=lambda x: x[0])

        # Mount scheduled event cards
        for next_run, event_type, agent_id, schedule in scheduled_events:
            sidebar_events.mount(ScheduledEventCard(event_type, agent_id, schedule, next_run))

        pending_table = self.query_one("#pending-table", QueueTable)
        running_table = self.query_one("#running-table", QueueTable)
        finished_table = self.query_one("#finished-table", QueueTable)

        pending_table.refresh_rows(pending, agent_labels)
        running_table.refresh_rows(running, agent_labels)
        finished_table.refresh_rows(finished, agent_labels)

        # Update section labels with counts
        self.query_one(".section-label.pending", Label).update(f"⏳  PENDING  [{len(pending)}]")
        self.query_one(".section-label.running", Label).update(f"▶   RUNNING  [{len(running)}]")
        self.query_one(".section-label.finished", Label).update(f"✔   RECENTLY FINISHED  [{len(finished)}]")
        self.query_one(".section-label.agents", Label).update(f"👥  AGENTS  [{len(all_agents)}]")
        self.query_one(".section-label.events", Label).update(f"📆  SCHEDULED EVENTS  [{len(scheduled_events)}]")

        # Refresh log panel
        self._refresh_log_panel()


async def run_tui() -> None:
    """Open the DB connection, start background processes, and launch the TUI."""
    settings = OrchestratorSettings()
    # Disable console logging for TUI to avoid interfering with display
    setup_logging(settings, enable_console=False)
    log_file = settings.logs_dir / "orchestrator.log"

    log = logging.getLogger(__name__)
    log.info("Starting TUI with background processes")

    async with OrchestratorDB(settings.db_path) as db:
        # Initialize vendors
        vendors: dict = {"claude_code": ClaudeCodeVendor(db)}

        # Create runners
        runner = QueueRunner(db, vendors, settings)
        poller = PollingRunner(db, settings.pollings)
        cron_runner = CronRunner(db, settings)

        # Create TUI app
        app = OrchestratorTUI(db, log_file, settings, runner, poller, cron_runner)

        # Start background tasks
        async def run_background_services() -> None:
            """Run all background services concurrently."""
            try:
                await asyncio.gather(
                    runner.run_forever(),
                    poller.run_forever(),
                    cron_runner.run_forever(),
                    serve_sse_async(settings.mcp_server_host, settings.mcp_server_port),
                )
            except asyncio.CancelledError:
                log.info("Background services cancelled")
                raise

        # Run TUI and background services concurrently
        bg_task = asyncio.create_task(run_background_services())
        try:
            await app.run_async()
        finally:
            # Cancel background services when TUI exits
            bg_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bg_task
            log.info("TUI and background processes stopped")
