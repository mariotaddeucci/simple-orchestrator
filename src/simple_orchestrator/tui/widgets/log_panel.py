from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Label, OptionList
from textual.widgets.option_list import Option

from simple_orchestrator.tui.utils import _LOG_LEVEL_STYLE, parse_log_line, tail_lines

if TYPE_CHECKING:
    from textual.app import ComposeResult

_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LOG_DISPLAY_LINES = 100
_LEVEL_HIERARCHY = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


class LogPanel(Container):
    DEFAULT_CSS = """
    LogPanel {
        height: 2fr;
        border: round #6272a4;
        background: #282a36;
        padding: 1;
        margin-top: 1;
    }
    LogPanel #log-header {
        height: auto;
        layout: horizontal;
        margin-bottom: 1;
    }
    LogPanel #log-level-selector {
        width: 20;
        height: 7;
        background: #44475a;
        border: round #6272a4;
        margin-left: 2;
    }
    LogPanel #log-level-selector > .option-list--option {
        color: #f8f8f2;
        padding: 0 1;
    }
    LogPanel #log-level-selector > .option-list--option-highlighted {
        background: #6272a4;
        color: #50fa7b;
    }
    LogPanel #log-display {
        height: 1fr;
        background: #282a36;
        color: #f8f8f2;
        border: none;
        padding: 0;
    }
    """

    selected_level: reactive[str] = reactive("INFO")

    def __init__(self, log_file: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log_file = log_file

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-header"):
            yield Label("📋  LOGS", classes="section-label logs")
            yield OptionList(
                *[Option(lvl, id=f"log-level-{lvl}") for lvl in _LOG_LEVELS],
                id="log-level-selector",
            )
        yield DataTable(id="log-display", show_cursor=False, zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#log-display", DataTable)
        table.add_column("Level", width=10)
        table.add_column("Timestamp", width=20)
        table.add_column("Logger", width=35)
        table.add_column("Message")

        selector = self.query_one("#log-level-selector", OptionList)
        for idx, option in enumerate(selector._options):
            if option.id == "log-level-INFO":
                selector.highlighted = idx
                break

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        level = (event.option.id or "log-level-INFO").replace("log-level-", "")
        self.selected_level = level
        self.refresh_logs()

    def refresh_logs(self) -> None:
        table = self.query_one("#log-display", DataTable)
        lines = tail_lines(self._log_file, _LOG_DISPLAY_LINES)
        min_level = _LEVEL_HIERARCHY.get(self.selected_level, 1)
        table.clear()
        for line in lines:
            ts, level, name, message = parse_log_line(line)
            if _LEVEL_HIERARCHY.get(level, 1) >= min_level:
                style = _LOG_LEVEL_STYLE.get(level, "white")
                table.add_row(f"[{style}]{level}[/]", ts, name, message)
