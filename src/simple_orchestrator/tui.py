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
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label, RichLog

from .db.orchestrator import OrchestratorDB
from .settings import OrchestratorSettings

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


class QueueTable(DataTable):
    """A DataTable that renders QueueItem rows for a specific status group."""

    # Column definitions: (column_id, header_label)
    _PENDING_COLS: ClassVar[list[tuple[str, str]]] = [
        ("id", "ID"),
        ("agent", "Agent"),
        ("prompt", "Prompt"),
        ("queued", "Queued At"),
    ]

    _RUNNING_COLS: ClassVar[list[tuple[str, str]]] = [
        ("id", "ID"),
        ("agent", "Agent"),
        ("prompt", "Prompt"),
        ("started", "Started At"),
        ("elapsed", "Elapsed"),
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
        super().__init__(show_cursor=False, zebra_stripes=True, **kwargs)
        self._mode = mode  # "pending" | "running" | "finished"
        self._col_keys: dict[str, ColumnKey] = {}

    def on_mount(self) -> None:
        cols = {"pending": self._PENDING_COLS, "running": self._RUNNING_COLS, "finished": self._FINISHED_COLS}[
            self._mode
        ]
        for col_id, label in cols:
            self._col_keys[col_id] = self.add_column(label, key=col_id)

    def refresh_rows(self, items: list[QueueItem], agent_labels: dict[str, str]) -> None:
        self.clear()
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
                )


class OrchestratorTUI(App[None]):
    """Textual TUI that displays the Simple Orchestrator queue."""

    TITLE = "Simple Orchestrator — Dashboard"
    CSS = """
    Screen {
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

    def compose(self) -> ComposeResult:
        yield Header()

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
        agent_labels: dict[str, str] = {a.id: a.nickname or a.name for a in db_agents}

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

        # Refresh log panel
        self._refresh_log_panel()


async def run_tui() -> None:
    """Open the DB connection and launch the TUI."""
    settings = OrchestratorSettings()
    log_file = settings.logs_dir / "orchestrator.log"
    async with OrchestratorDB(settings.db_path) as db:
        app = OrchestratorTUI(db, log_file)
        await app.run_async()
