"""
Terminal User Interface for monitoring the Simple Orchestrator queue.

Displays three panels (auto-refreshed every 2 s):
  • Pending   — items waiting to run
  • Running   — items currently being executed
  • Finished  — the last N completed/failed/killed/cancelled items

Launch via:
    simple-orchestrator tui
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label

from .db.orchestrator import OrchestratorDB
from .settings import OrchestratorSettings

if TYPE_CHECKING:
    from textual.binding import BindingType
    from textual.widgets._data_table import ColumnKey

    from .models.queue_item import QueueItem

_REFRESH_INTERVAL = 2.0  # seconds
_FINISHED_LIMIT = 20  # how many recent finished items to display

_STATUS_STYLE: dict[str, str] = {
    "pending": "yellow",
    "running": "cyan",
    "completed": "green",
    "failed": "red",
    "killed": "red",
    "cancelled": "dim",
}


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

    def refresh_rows(self, items: list[QueueItem]) -> None:
        self.clear()
        if not items:
            return

        if self._mode == "pending":
            for item in items:
                agent = item.agent_nickname or item.agent_id
                self.add_row(
                    _styled(item.id[-8:], item.status),
                    agent,
                    _truncate(item.prompt),
                    _fmt_dt(item.created_at),
                )
        elif self._mode == "running":
            for item in items:
                agent = item.agent_nickname or item.agent_id
                self.add_row(
                    _styled(item.id[-8:], item.status),
                    agent,
                    _truncate(item.prompt),
                    _fmt_dt(item.started_at),
                    _elapsed(item.started_at, None),
                )
        else:  # finished
            for item in items:
                agent = item.agent_nickname or item.agent_id
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

    .count {
        color: $text-muted;
        text-style: italic;
    }

    QueueTable {
        height: 1fr;
        border: none;
    }

    QueueTable.pending {
        height: 2fr;
    }

    QueueTable.finished {
        height: 3fr;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    _pending_count: reactive[int] = reactive(0)
    _running_count: reactive[int] = reactive(0)
    _finished_count: reactive[int] = reactive(0)

    def __init__(self, db: OrchestratorDB) -> None:
        super().__init__()
        self._db = db
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("⏳  PENDING", classes="section-label pending")
        yield QueueTable("pending", id="pending-table", classes="pending")
        yield Label("▶   RUNNING", classes="section-label running")
        yield QueueTable("running", id="running-table", classes="running")
        yield Label(f"✔   RECENTLY FINISHED (last {_FINISHED_LIMIT})", classes="section-label finished")
        yield QueueTable("finished", id="finished-table", classes="finished")
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

    async def _load_data(self) -> None:
        pending = await self._db.list_queue(status="pending")
        running = await self._db.list_queue(status="running")

        # Finished = completed + failed + killed + cancelled, newest first
        all_items = await self._db.list_queue()
        finished = [i for i in all_items if i.status in ("completed", "failed", "killed", "cancelled") and i.ended_at]
        finished.sort(key=lambda i: i.ended_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        finished = finished[:_FINISHED_LIMIT]

        pending_table = self.query_one("#pending-table", QueueTable)
        running_table = self.query_one("#running-table", QueueTable)
        finished_table = self.query_one("#finished-table", QueueTable)

        pending_table.refresh_rows(pending)
        running_table.refresh_rows(running)
        finished_table.refresh_rows(finished)

        # Update section labels with counts
        self.query_one(".section-label.pending", Label).update(f"⏳  PENDING  [{len(pending)}]")
        self.query_one(".section-label.running", Label).update(f"▶   RUNNING  [{len(running)}]")
        self.query_one(".section-label.finished", Label).update(f"✔   RECENTLY FINISHED  [{len(finished)}]")


async def run_tui() -> None:
    """Open the DB connection and launch the TUI."""
    settings = OrchestratorSettings()
    async with OrchestratorDB(settings.db_path) as db:
        app = OrchestratorTUI(db)
        await app.run_async()
