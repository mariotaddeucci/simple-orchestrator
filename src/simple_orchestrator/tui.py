"""
Terminal User Interface for monitoring the Simple Orchestrator queue.

Displays three columns (auto-refreshed every 2 s):
  • Pending   — items waiting to run
  • Running   — items currently being executed
  • Finished  — the last N completed/failed/killed/cancelled items

A log panel at the bottom shows recent entries from the orchestrator log file.

Launch via:
    simple-orchestrator tui
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, RichLog, Static, TextArea

from .db.orchestrator import OrchestratorDB
from .settings import OrchestratorSettings

if TYPE_CHECKING:
    from pathlib import Path

    from textual.binding import BindingType
    from textual.widgets._data_table import ColumnKey

    from .models.agent_record import AgentRecord
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

        async def handle_prompt(prompt: str | None) -> None:
            if prompt and isinstance(self.app, OrchestratorTUI):
                await self.app.enqueue_prompt(self.agent, prompt)

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

    /* ── Sidebar for agents ────────────────────────────────── */
    #sidebar {
        width: 25;
        border-right: solid $accent;
        background: $panel;
    }

    #sidebar-container {
        height: 1fr;
    }

    .section-label.agents {
        background: $primary;
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

    def __init__(self, db: OrchestratorDB, log_file: Path) -> None:
        super().__init__()
        self._db = db
        self._log_file = log_file
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._agents: list[AgentRecord] = []  # Store agents for interaction

    def compose(self) -> ComposeResult:
        yield Header()

        # Sidebar with agents
        with Vertical(id="sidebar"):
            yield Label("👥  AGENTS", classes="section-label agents")
            yield ScrollableContainer(id="sidebar-container")

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
        await self._db.enqueue(agent_id=agent.id, prompt=prompt)
        await self._load_data()

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

    async def _load_data(self) -> None:
        pending = await self._db.list_queue(status="pending")
        running = await self._db.list_queue(status="running")

        # Finished = completed + failed + killed + cancelled, newest first
        all_items = await self._db.list_queue()
        finished = [i for i in all_items if i.status in ("completed", "failed", "killed", "cancelled") and i.ended_at]
        finished.sort(key=lambda i: i.ended_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        finished = finished[:_FINISHED_LIMIT]

        # Build agent label map: prefer nickname over name, fall back to agent_id in display
        db_agents = await self._db.list_agents()
        self._agents = db_agents  # Store for later use
        agent_labels: dict[str, str] = {a.id: a.nickname or a.name for a in db_agents}

        # Update sidebar with agent cards
        sidebar = self.query_one("#sidebar-container", ScrollableContainer)
        sidebar.remove_children()
        for agent in db_agents:
            sidebar.mount(AgentCard(agent))

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
        self.query_one(".section-label.agents", Label).update(f"👥  AGENTS  [{len(db_agents)}]")

        # Refresh log panel
        self._refresh_log_panel()


async def run_tui() -> None:
    """Open the DB connection and launch the TUI."""
    settings = OrchestratorSettings()
    log_file = settings.logs_dir / "orchestrator.log"
    async with OrchestratorDB(settings.db_path) as db:
        app = OrchestratorTUI(db, log_file)
        await app.run_async()
