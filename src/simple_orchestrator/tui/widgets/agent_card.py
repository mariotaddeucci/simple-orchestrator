from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.widgets import Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from simple_orchestrator.models.agent_record import AgentRecord


class AgentCard(Static):
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
        yield Label(name, classes="agent-name")
        yield Label(f"[{self.agent.vendor}]", classes="agent-vendor")

    async def on_click(self) -> None:
        from simple_orchestrator.tui.app import OrchestratorTUI  # noqa: PLC0415
        from simple_orchestrator.tui.modals.prompt_modal import PromptModal  # noqa: PLC0415

        log = logging.getLogger(__name__)
        log.info("AgentCard clicked: %s", self.agent.id)

        if not isinstance(self.app, OrchestratorTUI):
            return

        agents = self.app.service.list_agents()

        async def handle(result: tuple[str, str | None, str | None] | None) -> None:
            if result and isinstance(self.app, OrchestratorTUI):
                prompt, workdir, _ = result
                self.app.do_enqueue(self.agent, prompt, workdir)

        await self.app.push_screen(PromptModal(self.agent, agents), handle)
