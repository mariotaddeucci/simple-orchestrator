from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, SelectionList, TextArea
from textual.widgets.selection_list import Selection

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from simple_orchestrator.models.agent_record import AgentRecord


class PromptModal(ModalScreen[tuple[str, str | None, str | None] | None]):
    DEFAULT_CSS = """
    PromptModal { align: center middle; }
    #prompt-dialog {
        width: 90; height: 45;
        border: round #bd93f9;
        background: #282a36;
        padding: 2;
    }
    #prompt-dialog .dialog-title {
        text-style: bold; color: #ff79c6;
        text-align: center; margin-bottom: 2; height: 3;
    }
    #agent-label { margin-bottom: 1; color: #f8f8f2; height: 2; }
    #agent-selector {
        height: 8; margin-bottom: 2;
        background: #44475a; border: round #6272a4;
    }
    #prompt-input {
        height: 12; margin-bottom: 2;
        background: #44475a; border: round #6272a4; padding: 1;
    }
    #workdir-label { margin-bottom: 1; margin-top: 2; color: #f8f8f2; height: 2; }
    #workdir-input {
        margin-bottom: 2;
        background: #44475a; border: round #6272a4;
        padding: 0 1; height: 3;
    }
    #button-container { layout: horizontal; height: 3; align: center middle; }
    #button-container Button { margin: 0 1; }
    SelectionList { background: #44475a; }
    SelectionList > .selection-list--button { color: #f8f8f2; }
    SelectionList > .selection-list--button-selected { background: #6272a4; color: #50fa7b; }
    """

    def __init__(
        self,
        agent: AgentRecord | None = None,
        agents: list[AgentRecord] | None = None,
    ) -> None:
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
            yield Label(
                "Working Directory (leave empty for default, 'null' for temp dir):",
                id="workdir-label",
            )
            workdir_value = self.agent.workdir if self.agent else ""
            yield Input(
                value=workdir_value or "",
                placeholder="Enter directory path or leave empty",
                id="workdir-input",
            )
            with Horizontal(id="button-container"):
                yield Button("Browse...", variant="default", id="browse-button")
                yield Button("OK", variant="primary", id="ok-button")
                yield Button("Cancel", variant="default", id="cancel-button")

    def _selected_agent_id(self) -> str | None:
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
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-button":
            prompt = self.query_one("#prompt-input", TextArea).text.strip()
            if not prompt:
                return
            workdir_raw = self.query_one("#workdir-input", Input).value.strip()
            workdir = None if not workdir_raw or workdir_raw.lower() == "null" else workdir_raw
            agent_id = self._selected_agent_id()
            if not self.agent and not agent_id:
                return
            self.dismiss((prompt, workdir, agent_id))
        elif event.button.id == "cancel-button":
            self.dismiss(None)
        elif event.button.id == "browse-button":
            self._browse()

    def _browse(self) -> None:
        from simple_orchestrator.tui.modals.directory_browser import DirectoryBrowser  # noqa: PLC0415

        workdir_input = self.query_one("#workdir-input", Input)
        current = workdir_input.value.strip()
        initial: str | None = None
        if current and current.lower() != "null":
            p = Path(current)
            if p.is_dir():
                initial = current
            elif p.parent.is_dir():
                initial = str(p.parent)

        async def handle(selected: str | None) -> None:
            if selected:
                workdir_input.value = selected

        self.app.push_screen(DirectoryBrowser(initial), handle)
