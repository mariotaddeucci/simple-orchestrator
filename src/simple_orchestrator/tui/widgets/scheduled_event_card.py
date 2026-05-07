from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Label, Static

from simple_orchestrator.tui.utils import format_next_run

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from simple_orchestrator.tui.service import ScheduledEvent


class ScheduledEventCard(Static):
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

    def __init__(self, event: ScheduledEvent, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._event = event

    def compose(self) -> ComposeResult:
        icon = "⏱️" if self._event.event_type == "polling" else "📅"
        yield Label(f"{icon} {self._event.event_type.upper()}", classes="event-type")
        yield Label(f"Agent: {self._event.agent_id}", classes="event-agent")
        yield Label(f"Next: {format_next_run(self._event.next_run)}", classes="event-next-run")
        yield Label(f"Schedule: {self._event.schedule}", classes="event-schedule")
