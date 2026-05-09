from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual import work
from textual.containers import Container, Horizontal
from textual.widgets import Button, Input, Label, RichLog

from simple_orchestrator.models.session import SessionConfig
from simple_orchestrator.vendor_selector import VendorModelSelection, parse_vendor_model_selection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from simple_orchestrator.settings import OrchestratorSettings
    from simple_orchestrator.vendors.base import BaseVendor


@dataclass
class _ChatMessage:
    role: str
    text: str


class ChatPanel(Container):
    DEFAULT_CSS = """
    ChatPanel {
        height: 1fr;
        border: round #6272a4;
        background: #282a36;
        padding: 1;
    }
    ChatPanel #chat-header {
        height: auto;
        layout: horizontal;
        margin-bottom: 1;
    }
    ChatPanel #model-selector {
        width: 1fr;
        background: #44475a;
        border: round #6272a4;
        padding: 0 1;
        height: 3;
        margin-left: 2;
    }
    ChatPanel #chat-log {
        height: 1fr;
        border: none;
        background: #282a36;
        color: #f8f8f2;
        padding: 0;
    }
    ChatPanel #chat-input-row {
        height: auto;
        layout: horizontal;
        margin-top: 1;
    }
    ChatPanel #chat-input {
        width: 1fr;
        background: #44475a;
        border: round #6272a4;
        padding: 0 1;
        height: 3;
    }
    ChatPanel #send-button {
        width: 12;
        margin-left: 1;
    }
    ChatPanel #clear-button {
        width: 12;
        margin-left: 1;
    }
    """

    def __init__(
        self,
        settings: OrchestratorSettings,
        vendors: dict[str, BaseVendor],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._settings = settings
        self._vendors = vendors
        self._history: list[_ChatMessage] = []
        self._running: bool = False

    def compose(self):
        with Horizontal(id="chat-header"):
            yield Label("💬  CHAT", classes="section-label")
            yield Input(
                value="claude-code/claude-sonnet-4-6",
                placeholder="provider/model (e.g. github-copilot/gpt-4.1)",
                id="model-selector",
            )
        yield RichLog(id="chat-log", wrap=True, highlight=False, markup=True)
        with Horizontal(id="chat-input-row"):
            yield Input(placeholder="Type a message and press Enter…", id="chat-input")
            yield Button("Send", variant="primary", id="send-button")
            yield Button("Clear", variant="default", id="clear-button")

    def on_mount(self) -> None:
        self.query_one("#chat-input", Input).focus()
        self._append_system(
            "Chat ready. Use provider/model like `claude-code/claude-sonnet-4-6` or `github-copilot/gpt-4.1`.",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-button":
            self._send_from_input()
        elif event.button.id == "clear-button":
            self._history.clear()
            self.query_one("#chat-log", RichLog).clear()
            self._append_system("Chat cleared.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            self._send_from_input()

    def _send_from_input(self) -> None:
        if self._running:
            return
        text = self.query_one("#chat-input", Input).value.strip()
        if not text:
            return
        self.query_one("#chat-input", Input).value = ""
        self._history.append(_ChatMessage(role="user", text=text))
        self._append_user(text)
        self._run_chat_turn(text)

    def _append_user(self, text: str) -> None:
        self.query_one("#chat-log", RichLog).write(f"[bold #f1fa8c]user:[/] {text}")

    def _append_assistant(self, text: str) -> None:
        self.query_one("#chat-log", RichLog).write(f"[bold #50fa7b]assistant:[/] {text}")

    def _append_system(self, text: str) -> None:
        self.query_one("#chat-log", RichLog).write(f"[#8be9fd]{text}[/]")

    def _build_prompt(self, user_text: str) -> str:
        # Simple iterative session: include a short transcript in the prompt.
        header = (
            "You are a helpful assistant running inside simple-orchestrator.\n"
            "You may use any available MCP tools when helpful (e.g. enqueue tasks, list tasks, check status).\n"
            "Keep responses concise and action-oriented.\n"
        )
        parts: list[str] = [header]
        for msg in self._history[-20:]:
            role = "User" if msg.role == "user" else "Assistant"
            parts.append(f"{role}: {msg.text}")
        parts.append(f"User: {user_text}")
        return "\n".join(parts).strip()

    def _selection(self) -> VendorModelSelection | None:
        raw = self.query_one("#model-selector", Input).value.strip()
        if not raw:
            return None
        try:
            return parse_vendor_model_selection(raw)
        except ValueError as exc:
            self._append_system(f"[red]Invalid provider/model:[/] {exc}")
            return None

    @work(name="chat-turn")
    async def _run_chat_turn(self, user_text: str) -> None:
        self._running = True
        try:
            selection = self._selection()
            if not selection:
                return

            vendor = self._vendors.get(selection.vendor)
            if not vendor:
                known = ", ".join(sorted(self._vendors.keys()))
                self._append_system(f"[red]Vendor '{selection.vendor}' not registered.[/] Known: {known}")
                return

            cfg = SessionConfig(
                prompt=self._build_prompt(user_text),
                model=selection.model,
                workdir=str(Path.cwd()),
                mcp_servers=dict(self._settings.mcp_servers),
                skills=list(self._settings.skills),
                max_turns=10,
            )

            stream = await vendor.execute_session(cfg)
            assistant_text = await self._collect_assistant_text(selection, stream)
            if assistant_text.strip():
                self._history.append(_ChatMessage(role="assistant", text=assistant_text.strip()))
                self._append_assistant(assistant_text.strip())
            else:
                self._append_system("[yellow]No assistant text content received.[/]")
        except Exception as exc:
            self._append_system(f"[red]Chat error:[/] {exc}")
        finally:
            self._running = False

    async def _collect_assistant_text(
        self,
        selection: VendorModelSelection,
        stream: AsyncIterator[Any],
    ) -> str:
        if selection.vendor == "claude_code":
            return await self._collect_claude_text(stream)
        if selection.vendor == "github_copilot":
            return await self._collect_copilot_text(stream)
        if selection.vendor == "opencode":
            return await self._collect_opencode_text(stream)
        return await self._collect_fallback_text(stream)

    async def _collect_claude_text(self, stream: AsyncIterator[Any]) -> str:
        from claude_agent_sdk import AssistantMessage, TextBlock  # noqa: PLC0415

        parts: list[str] = []
        async for msg in stream:
            if isinstance(msg, AssistantMessage):
                parts.extend(
                    block.text for block in msg.content if isinstance(block, TextBlock) and block.text is not None
                )
        return "\n".join(p.strip() for p in parts if p.strip())

    async def _collect_copilot_text(self, stream: AsyncIterator[Any]) -> str:
        parts: list[str] = []
        async for event in stream:
            if isinstance(event, dict) and event.get("type") == "session_created":
                continue
            if not isinstance(event, dict) or event.get("type") != "event":
                continue
            data = event.get("data")
            content = getattr(getattr(data, "data", None), "content", None)
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
        return "\n".join(parts)

    async def _collect_opencode_text(self, stream: AsyncIterator[Any]) -> str:
        parts: list[str] = []
        async for event in stream:
            parts.extend(_extract_opencode_response_text(event))
        return "\n".join(parts)

    async def _collect_fallback_text(self, stream: AsyncIterator[Any]) -> str:
        parts = [str(item) async for item in stream]
        return "\n".join(parts)


def _extract_opencode_response_text(event: object) -> list[str]:
    if not isinstance(event, dict) or event.get("type") != "response":
        return []
    msg = event.get("data")
    raw_parts = getattr(msg, "parts", None)
    if not raw_parts:
        return []
    out: list[str] = []
    for part in raw_parts:
        text = getattr(part, "text", None)
        if isinstance(text, str):
            text = text.strip()
            if text:
                out.append(text)
    return out
