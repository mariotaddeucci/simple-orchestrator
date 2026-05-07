from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult


class CommandPalette(ModalScreen[str | None]):
    DEFAULT_CSS = """
    CommandPalette { align: center middle; }
    #command-dialog {
        width: 70; height: 30;
        border: round #bd93f9;
        background: #282a36;
        padding: 2;
    }
    #command-dialog .dialog-title {
        text-style: bold; color: #ff79c6;
        text-align: center; margin-bottom: 2; height: 3;
    }
    #command-list {
        height: 1fr;
        background: #44475a;
        border: round #6272a4;
    }
    OptionList { background: #44475a; }
    OptionList > .option-list--option { color: #f8f8f2; padding: 1 2; }
    OptionList > .option-list--option-highlighted { background: #6272a4; color: #50fa7b; }
    """

    def compose(self) -> ComposeResult:
        with Container(id="command-dialog"):
            yield Label("⚡ Command Palette", classes="dialog-title")
            yield OptionList(
                Option("📝 Delegate Task to Agent", id="delegate-task"),
                Option("🔄 Refresh View", id="refresh"),
                Option("📊 View Queue Stats", id="queue-stats"),
                Option("❌ Close Palette", id="close"),
                id="command-list",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)
