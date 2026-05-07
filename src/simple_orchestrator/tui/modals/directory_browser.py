from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class DirectoryBrowser(ModalScreen[str | None]):
    DEFAULT_CSS = """
    DirectoryBrowser { align: center middle; }
    #browser-dialog {
        width: 80; height: 35;
        border: round #bd93f9;
        background: #282a36;
        padding: 2;
    }
    #browser-dialog .dialog-title {
        text-style: bold; color: #ff79c6;
        text-align: center; margin-bottom: 2; height: 3;
    }
    #directory-tree {
        height: 1fr; margin-bottom: 2;
        background: #44475a; border: round #6272a4; padding: 1;
    }
    #browser-button-container {
        layout: horizontal; height: 3; align: center middle;
    }
    #browser-button-container Button { margin: 0 1; }
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
                self.dismiss(str(tree.cursor_node.data.path))
            else:
                self.dismiss(self.initial_path)
        elif event.button.id == "cancel-button":
            self.dismiss(None)
