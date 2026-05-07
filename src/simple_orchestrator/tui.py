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

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from croniter import croniter
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    SelectionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from .cron_runner import CronRunner
from .db.orchestrator import OrchestratorDB
from .logging_config import get_internal_logger, setup_logging
from .mcp_server import serve_sse_async
from .models.agent_record import AgentRecord
from .polling_runner import PollingRunner
from .queue_runner import QueueRunner
from .settings import OrchestratorSettings
from .vendors import ClaudeCodeVendor

if TYPE_CHECKING:
    from textual.binding import BindingType
    from textual.widgets._data_table import ColumnKey

    from .models.queue_item import QueueItem

_REFRESH_INTERVAL = 2.0  # seconds
_FINISHED_LIMIT = 20  # how many recent finished items to display
_LOG_DISPLAY_LINES = 100  # max lines shown in the log panel
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_STATUS_STYLE: dict[str, str] = {
    "pending": "#f1fa8c",  # Dracula yellow
    "running": "#8be9fd",  # Dracula cyan
    "completed": "#50fa7b",  # Dracula green
    "failed": "#ff5555",  # Dracula red
    "killed": "#ff5555",  # Dracula red
    "cancelled": "#6272a4",  # Dracula comment (dim)
}

_LOG_LEVEL_STYLE: dict[str, str] = {
    "DEBUG": "#6272a4",  # Dracula comment
    "INFO": "#f8f8f2",  # Dracula foreground
    "WARNING": "#ffb86c",  # Dracula orange
    "ERROR": "bold #ff5555",  # Dracula red
    "CRITICAL": "bold #ff5555 on #44475a",  # Red on current line
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
        border: round #bd93f9;
        background: #44475a;
        padding: 1 2;
        margin: 1 1;
    }

    ScheduledEventCard .event-type {
        text-style: bold;
        color: #ffb86c;
    }

    ScheduledEventCard .event-agent {
        color: #f8f8f2;
    }

    ScheduledEventCard .event-next-run {
        color: #50fa7b;
        text-style: italic;
    }

    ScheduledEventCard .event-schedule {
        color: #6272a4;
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
        border: round #bd93f9;
        background: #44475a;
        padding: 1 2;
        margin: 1 1;
    }

    AgentCard:hover {
        border: round #50fa7b;
        background: #6272a4;
    }

    AgentCard .agent-name {
        text-style: bold;
        color: #f8f8f2;
    }

    AgentCard .agent-vendor {
        color: #8be9fd;
        text-style: italic;
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

        # Get all agents from the app
        agents = self.app._agents if isinstance(self.app, OrchestratorTUI) else []

        async def handle_prompt(result: tuple[str, str | None, str | None] | None) -> None:
            log.info("handle_prompt callback invoked with result: %s", result)
            if result and isinstance(self.app, OrchestratorTUI):
                prompt, workdir, _agent_id = result
                # agent_id should be None since agent is pre-selected
                log.info("Calling enqueue_prompt for agent %s with workdir %s", self.agent.id, workdir)
                self.app.enqueue_prompt(self.agent, prompt, workdir)
                log.info("enqueue_prompt completed for agent %s", self.agent.id)

        await self.app.push_screen(PromptModal(self.agent, agents), handle_prompt)


class DirectoryBrowser(ModalScreen[str | None]):
    """Modal screen for browsing and selecting a directory."""

    DEFAULT_CSS = """
    DirectoryBrowser {
        align: center middle;
    }

    #browser-dialog {
        width: 80;
        height: 35;
        border: round #bd93f9;
        background: #282a36;
        padding: 2;
    }

    #browser-dialog .dialog-title {
        text-style: bold;
        color: #ff79c6;
        text-align: center;
        margin-bottom: 2;
        height: 3;
    }

    #directory-tree {
        height: 1fr;
        margin-bottom: 2;
        background: #44475a;
        border: round #6272a4;
        padding: 1;
    }

    #browser-button-container {
        layout: horizontal;
        height: 3;
        align: center middle;
    }

    #browser-button-container Button {
        margin: 0 1;
    }
    """

    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.initial_path = initial_path or str(Path.cwd())

    def compose(self) -> ComposeResult:
        with Container(id="browser-dialog"):
            yield Label("Select Directory", classes="dialog-title")
            yield DirectoryTree(self.initial_path, id="directory-tree")
            with Horizontal(id="browser-button-container"):
                yield Button("Select", variant="primary", id="select-button")
                yield Button("Cancel", variant="default", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-button":
            tree = self.query_one("#directory-tree", DirectoryTree)
            if tree.cursor_node and tree.cursor_node.data:
                selected_path = str(tree.cursor_node.data.path)
                self.dismiss(selected_path)
            else:
                self.dismiss(self.initial_path)
        elif event.button.id == "cancel-button":
            self.dismiss(None)


class CommandPalette(ModalScreen[str | None]):
    """Command palette modal for quick actions (Ctrl+P)."""

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }

    #command-dialog {
        width: 70;
        height: 30;
        border: round #bd93f9;
        background: #282a36;
        padding: 2;
    }

    #command-dialog .dialog-title {
        text-style: bold;
        color: #ff79c6;
        text-align: center;
        margin-bottom: 2;
        height: 3;
    }

    #command-list {
        height: 1fr;
        background: #44475a;
        border: round #6272a4;
    }

    OptionList {
        background: #44475a;
    }

    OptionList > .option-list--option {
        color: #f8f8f2;
        padding: 1 2;
    }

    OptionList > .option-list--option-highlighted {
        background: #6272a4;
        color: #50fa7b;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="command-dialog"):
            yield Label("⚡ Command Palette", classes="dialog-title")
            yield OptionList(
                Option("📝 Delegate Task to Agent", id="delegate-task"),
                Option("🔄 Refresh View", id="refresh"),
                Option("📊 View Queue Stats", id="queue-stats"),
                Option("⚙️  Open Settings", id="settings"),
                Option("❌ Close Palette", id="close"),
                id="command-list",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)


class PromptModal(ModalScreen[tuple[str, str | None, str | None] | None]):
    """Modal screen for entering a prompt for an agent.

    Returns: (prompt, workdir, agent_id) or None if cancelled.
    If agent is pre-selected, agent_id will be None (use the pre-selected agent).
    """

    DEFAULT_CSS = """
    PromptModal {
        align: center middle;
    }

    #prompt-dialog {
        width: 90;
        height: 45;
        border: round #bd93f9;
        background: #282a36;
        padding: 2;
    }

    #prompt-dialog .dialog-title {
        text-style: bold;
        color: #ff79c6;
        text-align: center;
        margin-bottom: 2;
        height: 3;
    }

    #agent-label {
        margin-bottom: 1;
        color: #f8f8f2;
        height: 2;
    }

    #agent-selector {
        height: 8;
        margin-bottom: 2;
        background: #44475a;
        border: round #6272a4;
    }

    #prompt-input {
        height: 12;
        margin-bottom: 2;
        background: #44475a;
        border: round #6272a4;
        padding: 1;
    }

    #workdir-label {
        margin-bottom: 1;
        margin-top: 2;
        color: #f8f8f2;
        height: 2;
    }

    #workdir-input {
        margin-bottom: 2;
        background: #44475a;
        border: round #6272a4;
        padding: 0 1;
        height: 3;
    }

    #button-container {
        layout: horizontal;
        height: 3;
        align: center middle;
    }

    #button-container Button {
        margin: 0 1;
    }

    SelectionList {
        background: #44475a;
    }

    SelectionList > .selection-list--button {
        color: #f8f8f2;
    }

    SelectionList > .selection-list--button-selected {
        background: #6272a4;
        color: #50fa7b;
    }
    """

    def __init__(self, agent: AgentRecord | None = None, agents: list[AgentRecord] | None = None) -> None:
        super().__init__()
        self.agent = agent
        self.agents = agents or []

    def compose(self) -> ComposeResult:
        with Container(id="prompt-dialog"):
            if self.agent:
                name = self.agent.nickname or self.agent.name
                yield Label(f"Enter prompt for: {name}", classes="dialog-title")
            else:
                yield Label("Delegate Task to Agent", classes="dialog-title")
                yield Label("Select Agent:", id="agent-label")
                # Create selection list with agents
                selections = [
                    Selection(
                        f"{a.nickname or a.name} [{a.vendor}]",
                        a.id,
                        a.id == (self.agent.id if self.agent else None),
                    )
                    for a in self.agents
                ]
                yield SelectionList(*selections, id="agent-selector")

            yield TextArea(id="prompt-input", language="markdown")
            yield Label("Working Directory (leave empty for default, enter 'null' for temp dir):", id="workdir-label")
            workdir_value = self.agent.workdir if self.agent else ""
            yield Input(
                value=workdir_value,
                placeholder="Enter directory path or leave empty",
                id="workdir-input",
            )
            with Horizontal(id="button-container"):
                yield Button("Browse...", variant="default", id="browse-button")
                yield Button("OK", variant="primary", id="ok-button")
                yield Button("Cancel", variant="default", id="cancel-button")

    def _get_selected_agent_id(self) -> str | None:
        """Get the selected agent ID from the selector, if available."""
        if self.agent or not self.agents:
            return None

        try:
            selector = self.query_one("#agent-selector", SelectionList)
            selected = selector.selected
            if not selected:
                self.app.notify("Please select an agent", severity="warning")
                return None
            return next(iter(selected))
        except Exception:
            # No selector if agent was pre-selected
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-button":
            text_area = self.query_one("#prompt-input", TextArea)
            prompt = text_area.text.strip()
            if not prompt:
                return

            workdir_input = self.query_one("#workdir-input", Input)
            workdir_value = workdir_input.value.strip()

            # Process workdir: empty string or 'null' means None
            workdir = None if not workdir_value or workdir_value.lower() == "null" else workdir_value

            # Get selected agent ID if no agent was pre-selected
            agent_id = self._get_selected_agent_id()
            if not self.agent and not agent_id:
                return  # Notification already shown in _get_selected_agent_id

            self.dismiss((prompt, workdir, agent_id))
        elif event.button.id == "cancel-button":
            self.dismiss(None)
        elif event.button.id == "browse-button":
            self._browse_directory()

    def _browse_directory(self) -> None:
        """Open directory browser modal."""
        workdir_input = self.query_one("#workdir-input", Input)
        current_value = workdir_input.value.strip()

        # Use current value as initial path if it's a valid directory
        initial_path: str | None = None
        if current_value and current_value.lower() != "null":
            path = Path(current_value)
            if path.is_dir():
                initial_path = current_value
            elif path.parent.is_dir():
                initial_path = str(path.parent)

        async def handle_selection(selected: str | None) -> None:
            if selected:
                workdir_input.value = selected

        self.app.push_screen(DirectoryBrowser(initial_path), handle_selection)


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
                    "[#ff5555]✕ Cancel[/]",
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
                    "[#ff5555]✕ Kill[/]",
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
        background: #282a36;
    }

    /* ── Sidebar for agents and scheduled events ───────────── */
    #sidebar {
        width: 35;
        border-right: round #bd93f9;
        background: #282a36;
        padding: 1;
    }

    #sidebar-agents {
        height: auto;
        max-height: 50%;
        background: #282a36;
        border: round #6272a4;
        padding: 1;
        margin: 1 0;
    }

    #sidebar-events {
        height: auto;
        max-height: 50%;
        background: #282a36;
        border: round #6272a4;
        padding: 1;
        margin: 1 0;
    }

    .section-label.agents {
        background: transparent;
        color: #bd93f9;
        text-style: bold;
        padding: 0 1;
        height: auto;
    }

    .section-label.events {
        background: transparent;
        color: #ffb86c;
        text-style: bold;
        padding: 0 1;
        height: auto;
    }

    /* ── Main content area ────────────────────────────────── */
    #main-content {
        width: 1fr;
        layout: vertical;
        background: #282a36;
        padding: 1;
    }

    /* ── Three-column queue area ────────────────────────────── */
    #columns {
        height: 3fr;
        margin-bottom: 1;
    }

    .col {
        width: 1fr;
        layout: vertical;
        border: round #44475a;
        margin: 0 1;
        padding: 1;
    }

    .col:first-of-type {
        margin-left: 0;
    }

    .col:last-of-type {
        margin-right: 0;
    }

    /* ── Section label strip ────────────────────────────────── */
    .section-label {
        background: transparent;
        color: #f8f8f2;
        padding: 0 0 1 0;
        text-style: bold;
        height: auto;
    }

    .section-label.pending {
        background: transparent;
        color: #f1fa8c;
    }

    .section-label.running {
        background: transparent;
        color: #50fa7b;
    }

    .section-label.finished {
        background: transparent;
        color: #8be9fd;
    }

    .section-label.logs {
        background: transparent;
        color: #ff79c6;
    }

    QueueTable {
        height: 1fr;
        border: none;
        background: #282a36;
        padding: 0;
    }

    /* ── Log panel ──────────────────────────────────────────── */
    #log-panel {
        height: 2fr;
        border: round #6272a4;
        background: #282a36;
        padding: 1;
        margin-top: 1;
    }

    #log-header {
        height: auto;
        layout: horizontal;
        margin-bottom: 1;
    }

    #log-level-selector {
        width: 20;
        height: 7;
        background: #44475a;
        border: round #6272a4;
        margin-left: 2;
    }

    #log-level-selector > .option-list--option {
        color: #f8f8f2;
        padding: 0 1;
    }

    #log-level-selector > .option-list--option-highlighted {
        background: #6272a4;
        color: #50fa7b;
    }

    #log-display {
        height: 1fr;
        background: #282a36;
        color: #f8f8f2;
        border: none;
        padding: 0;
    }

    /* ── Header and Footer styling ──────────────────────────── */
    Header {
        background: #44475a;
        color: #f8f8f2;
    }

    Footer {
        background: #44475a;
        color: #f8f8f2;
    }

    /* ── Button styling ────────────────────────────────────── */
    Button {
        background: #44475a;
        color: #f8f8f2;
        border: round #bd93f9;
        min-width: 12;
        height: 3;
    }

    Button:hover {
        background: #bd93f9;
        color: #282a36;
    }

    Button.-primary {
        background: #50fa7b;
        color: #282a36;
        border: round #50fa7b;
    }

    Button.-primary:hover {
        background: #50fa7b;
        color: #282a36;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("ctrl+p", "command_palette", "Commands"),
    ]

    _pending_count: reactive[int] = reactive(0)
    _running_count: reactive[int] = reactive(0)
    _finished_count: reactive[int] = reactive(0)
    _selected_log_level: reactive[str] = reactive("INFO")

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
        self._agents: list[AgentRecord] = []  # Store agents for interaction
        self._runner = runner
        self._poller = poller
        self._cron_runner = cron_runner

    def compose(self) -> ComposeResult:
        yield Header()

        # Sidebar with agents and scheduled events
        with Vertical(id="sidebar"):
            with ScrollableContainer(id="sidebar-agents"):
                yield Label("👥  AGENTS", classes="section-label agents")
            with ScrollableContainer(id="sidebar-events"):
                yield Label("📆  SCHEDULED EVENTS", classes="section-label events")

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

            with Container(id="log-panel"):
                with Horizontal(id="log-header"):
                    yield Label("📋  LOGS", classes="section-label logs")
                    yield OptionList(
                        *[Option(level, id=f"log-level-{level}") for level in _LOG_LEVELS],
                        id="log-level-selector",
                    )
                yield DataTable(id="log-display", show_cursor=False, zebra_stripes=True)

        yield Footer()

    def on_mount(self) -> None:
        # Initialize log DataTable columns
        log_table = self.query_one("#log-display", DataTable)
        log_table.add_column("Level", width=10)
        log_table.add_column("Timestamp", width=20)
        log_table.add_column("Logger", width=35)
        log_table.add_column("Message")

        # Set initial log level selection
        log_selector = self.query_one("#log-level-selector", OptionList)
        # Find and highlight INFO option
        for idx, option in enumerate(log_selector._options):
            if option.id == "log-level-INFO":
                log_selector.highlighted = idx
                break

        self.set_interval(_REFRESH_INTERVAL, self._do_refresh)
        # Immediate sync load
        self._load_data()
        # Start background workers
        self._run_queue_worker()
        self._run_cron_worker()
        self._run_polling_worker()
        self._run_mcp_server()

    def on_unmount(self) -> None:
        if self._runner:
            self._runner.stop()
        if self._cron_runner:
            self._cron_runner.stop()
        if self._poller:
            self._poller.stop()

    @work(name="queue-runner", exclusive=True)
    async def _run_queue_worker(self) -> None:
        if self._runner:
            await self._runner.start()

    @work(name="cron-runner", exclusive=True)
    async def _run_cron_worker(self) -> None:
        if self._cron_runner:
            await self._cron_runner.start()

    @work(name="polling-runner", exclusive=True)
    async def _run_polling_worker(self) -> None:
        if self._poller:
            await self._poller.start()

    @work(name="mcp-server", exclusive=True)
    async def _run_mcp_server(self) -> None:
        await serve_sse_async(self._settings.mcp_server_host, self._settings.mcp_server_port)

    def action_refresh(self) -> None:
        self._load_data()

    def _handle_delegate_task_command(self) -> None:
        """Handle the delegate-task command from the command palette."""

        async def handle_prompt(result: tuple[str, str | None, str | None] | None) -> None:
            if not result:
                return
            prompt, workdir, agent_id = result
            if not agent_id:
                self.notify("Please select an agent", severity="warning")
                return
            agent = next((a for a in self._agents if a.id == agent_id), None)
            if not agent:
                self.notify("Agent not found", severity="error")
                return
            self.enqueue_prompt(agent, prompt, workdir)

        self.push_screen(PromptModal(None, self._agents), handle_prompt)

    def _handle_queue_stats_command(self) -> None:
        """Handle the queue-stats command from the command palette."""
        pending = len(self._db.list_queue(status="pending"))
        running = len(self._db.list_queue(status="running"))
        all_items = self._db.list_queue()
        completed = len([i for i in all_items if i.status == "completed"])
        failed = len([i for i in all_items if i.status == "failed"])
        self.notify(
            f"Pending: {pending} | Running: {running} | Completed: {completed} | Failed: {failed}",
            title="Queue Statistics",
            timeout=5,
        )

    def action_command_palette(self) -> None:
        """Show the command palette (Ctrl+P)."""

        async def handle_command(command_id: str | None) -> None:
            if command_id == "delegate-task":
                self._handle_delegate_task_command()
            elif command_id == "refresh":
                self._load_data()
            elif command_id == "queue-stats":
                self._handle_queue_stats_command()

        self.push_screen(CommandPalette(), handle_command)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle log level selection."""
        if event.option_list.id == "log-level-selector":
            # Extract level from option ID (e.g., "log-level-DEBUG" -> "DEBUG")
            level = event.option.id.replace("log-level-", "") if event.option.id else "INFO"
            self._selected_log_level = level
            self._refresh_log_panel()

    def _do_refresh(self) -> None:
        self._load_data()

    def enqueue_prompt(self, agent: AgentRecord, prompt: str, workdir: str | None = None) -> None:
        """Enqueue a new task for the given agent with the provided prompt and optional workdir."""
        log = logging.getLogger(__name__)
        log.info("TUI enqueue_prompt: agent_id=%s, prompt=%s, workdir=%s", agent.id, prompt[:50], workdir)
        item = self._db.enqueue(agent_id=agent.id, prompt=prompt, workdir=workdir)
        log.info(
            "TUI enqueue_prompt: item created with id=%s, status=%s, workdir=%s",
            item.id,
            item.status,
            item.workdir,
        )
        # Show notification to user
        agent_name = agent.nickname or agent.name
        self.notify(
            f"✓ Task enqueued for {agent_name}",
            title="Task Added",
            severity="information",
            timeout=3,
        )
        self._load_data()
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

        if table._mode == "pending":
            self._cancel_item(item_id)
        elif table._mode == "running":
            self._kill_item(item)

    def _cancel_item(self, item_id: str) -> None:
        """Cancel a pending queue item."""
        self._db.cancel_queue_item(item_id)
        self._load_data()

    def _kill_item(self, item: QueueItem) -> None:
        """Kill a running queue item by killing its session."""
        if not item.session_id:
            return
        self._db.update_queue_item(
            item.id,
            status="killed",
            ended_at=datetime.now(UTC),
        )
        self._load_data()

    def _refresh_log_panel(self) -> None:
        """Read the log file tail and repopulate the log DataTable with level filtering."""
        log_table = self.query_one("#log-display", DataTable)
        lines = _tail_lines(self._log_file, _LOG_DISPLAY_LINES)

        # Define log level hierarchy for filtering
        level_hierarchy = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
        min_level = level_hierarchy.get(self._selected_log_level, 1)

        log_table.clear()
        for line in lines:
            ts, level, name, message = _parse_log_line(line)
            # Filter by selected log level
            if level_hierarchy.get(level, 1) >= min_level:
                style = _LOG_LEVEL_STYLE.get(level, "white")
                styled_level = f"[{style}]{level}[/]"
                log_table.add_row(styled_level, ts, name, message)

    def _merge_agents(self) -> list[AgentRecord]:
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

    def _load_data(self) -> None:  # noqa: C901
        pending = self._db.list_queue(status="pending")
        running = self._db.list_queue(status="running")

        # Finished = completed + failed + killed + cancelled, newest first
        all_items = self._db.list_queue()
        finished = [i for i in all_items if i.status in ("completed", "failed", "killed", "cancelled") and i.ended_at]
        finished.sort(key=lambda i: i.ended_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        finished = finished[:_FINISHED_LIMIT]

        # Merge agents from settings and DB (settings take priority, matching QueueRunner behavior)
        all_agents = self._merge_agents()
        self._agents = all_agents  # Store for later use
        agent_labels: dict[str, str] = {a.id: a.nickname or a.name for a in all_agents}

        # Update sidebar with agent cards
        sidebar_agents = self.query_one("#sidebar-agents", ScrollableContainer)
        # Remove all children except the label (first child)
        children = list(sidebar_agents.children)
        for child in children[1:]:  # Keep first child (label), remove rest
            child.remove()
        for agent in all_agents:
            sidebar_agents.mount(AgentCard(agent))

        # Update sidebar with scheduled events
        sidebar_events = self.query_one("#sidebar-events", ScrollableContainer)
        # Remove all children except the label (first child)
        children = list(sidebar_events.children)
        for child in children[1:]:  # Keep first child (label), remove rest
            child.remove()

        # Collect all scheduled events with their next run times
        scheduled_events: list[tuple[datetime, str, str, str]] = []  # (next_run, type, agent_id, schedule)

        # Add polling events
        for polling in self._settings.pollings:
            now = datetime.now(UTC)
            # Calculate next run based on interval
            # Use a key for tracking last run time (similar to cron)
            key = f"polling_{polling.agent_id}_{polling.prompt}"
            last_run = self._db.get_cron_last_run(key)
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
            last_run = self._db.get_cron_last_run(key)
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


def run_tui() -> None:
    """Open the DB connection, start background processes, and launch the TUI."""
    settings = OrchestratorSettings()
    # Disable console logging for TUI to avoid interfering with display
    setup_logging(settings.logs_dir, settings.log_level, enable_console=False)
    log_file = settings.logs_dir / "orchestrator.log"

    log = get_internal_logger(__name__)
    log.info("Starting TUI with background processes")

    with OrchestratorDB(settings.db_path) as db:
        # Initialize vendors
        vendors: dict = {"claude_code": ClaudeCodeVendor(db)}

        # Create runners
        runner = QueueRunner(db, vendors, settings)
        poller = PollingRunner(db, settings.pollings)
        cron_runner = CronRunner(db, settings)

        # Create TUI app
        app = OrchestratorTUI(db, log_file, settings, runner, poller, cron_runner)
        app.run()

    log.info("TUI and background processes stopped")
