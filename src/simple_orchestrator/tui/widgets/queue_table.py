from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from textual.widgets import DataTable

from simple_orchestrator.tui.utils import elapsed, fmt_dt, styled, truncate

if TYPE_CHECKING:
    from textual.widgets._data_table import ColumnKey

    from simple_orchestrator.models.queue_item import QueueItem


class QueueTable(DataTable):
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
        self._mode = mode
        self._col_keys: dict[str, ColumnKey] = {}
        self._items: list[QueueItem] = []

    def on_mount(self) -> None:
        cols = {"pending": self._PENDING_COLS, "running": self._RUNNING_COLS, "finished": self._FINISHED_COLS}[
            self._mode
        ]
        for col_id, label in cols:
            self._col_keys[col_id] = self.add_column(label, key=col_id)

    def refresh_rows(self, items: list[QueueItem], agent_labels: dict[str, str]) -> None:
        self.clear()
        self._items = items
        if not items:
            return

        if self._mode == "pending":
            for item in items:
                agent = agent_labels.get(item.agent_id, item.agent_id)
                self.add_row(
                    styled(item.id[-8:], item.status),
                    agent,
                    truncate(item.prompt),
                    fmt_dt(item.created_at),
                    "[#ff5555]✕ Cancel[/]",
                    key=item.id,
                )
        elif self._mode == "running":
            for item in items:
                agent = agent_labels.get(item.agent_id, item.agent_id)
                self.add_row(
                    styled(item.id[-8:], item.status),
                    agent,
                    truncate(item.prompt),
                    fmt_dt(item.started_at),
                    elapsed(item.started_at, None),
                    "[#ff5555]✕ Kill[/]",
                    key=item.id,
                )
        else:
            for item in items:
                agent = agent_labels.get(item.agent_id, item.agent_id)
                self.add_row(
                    item.id[-8:],
                    agent,
                    styled(item.status.upper(), item.status),
                    truncate(item.prompt),
                    fmt_dt(item.ended_at),
                    elapsed(item.started_at, item.ended_at),
                    key=item.id,
                )
