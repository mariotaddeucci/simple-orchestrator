from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import work
from textual.containers import Container, Horizontal
from textual.widgets import Button, Input, Label, RichLog


@dataclass
class _TerminalState:
    cwd: Path


class TerminalPanel(Container):
    DEFAULT_CSS = """
    TerminalPanel {
        height: 1fr;
        border: round #6272a4;
        background: #282a36;
        padding: 1;
    }
    TerminalPanel #terminal-header {
        height: auto;
        layout: horizontal;
        margin-bottom: 1;
    }
    TerminalPanel #terminal-cwd {
        width: 1fr;
        color: #8be9fd;
        padding: 0 1;
        height: auto;
    }
    TerminalPanel #terminal-log {
        height: 1fr;
        border: none;
        background: #282a36;
        color: #f8f8f2;
        padding: 0;
    }
    TerminalPanel #terminal-input-row {
        height: auto;
        layout: horizontal;
        margin-top: 1;
    }
    TerminalPanel #terminal-input {
        width: 1fr;
        background: #44475a;
        border: round #6272a4;
        padding: 0 1;
        height: 3;
    }
    TerminalPanel #run-button {
        width: 12;
        margin-left: 1;
    }
    TerminalPanel #terminal-clear {
        width: 12;
        margin-left: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state = _TerminalState(cwd=Path.cwd())
        self._running: bool = False

    def compose(self):
        with Horizontal(id="terminal-header"):
            yield Label("🖥️  TERMINAL", classes="section-label")
            yield Label(str(self._state.cwd), id="terminal-cwd")
        yield RichLog(id="terminal-log", wrap=True, highlight=False, markup=True)
        with Horizontal(id="terminal-input-row"):
            yield Input(placeholder="Command (e.g. uv run pytest -q)", id="terminal-input")
            yield Button("Run", variant="primary", id="run-button")
            yield Button("Clear", variant="default", id="terminal-clear")

    def on_mount(self) -> None:
        self.query_one("#terminal-input", Input).focus()
        self._write_system("Terminal ready. Use `cd <dir>` to change directory for subsequent commands.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-button":
            self._run_from_input()
        elif event.button.id == "terminal-clear":
            self.query_one("#terminal-log", RichLog).clear()
            self._write_system("Terminal cleared.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "terminal-input":
            self._run_from_input()

    def _run_from_input(self) -> None:
        if self._running:
            return
        cmd = self.query_one("#terminal-input", Input).value.strip()
        if not cmd:
            return
        self.query_one("#terminal-input", Input).value = ""
        self._write_command(cmd)
        self._run_command(cmd)

    def _write_command(self, cmd: str) -> None:
        self.query_one("#terminal-log", RichLog).write(f"[bold #f1fa8c]$[/] {cmd}")

    def _write_output(self, text: str) -> None:
        self.query_one("#terminal-log", RichLog).write(text.rstrip())

    def _write_system(self, text: str) -> None:
        self.query_one("#terminal-log", RichLog).write(f"[#8be9fd]{text}[/]")

    def _set_cwd(self, new_cwd: Path) -> None:
        self._state.cwd = new_cwd
        self.query_one("#terminal-cwd", Label).update(str(self._state.cwd))

    @work(name="terminal-run")
    async def _run_command(self, cmd: str) -> None:
        self._running = True
        try:
            if cmd.startswith("cd "):
                target = cmd[3:].strip()
                if not target:
                    self._write_system("Usage: cd <dir>")
                    return
                p = (self._state.cwd / target).resolve()
                if not p.is_dir():
                    self._write_system(f"[red]Not a directory:[/] {p}")
                    return
                self._set_cwd(p)
                return

            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(self._state.cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if stdout:
                self._write_output(stdout.decode(errors="replace"))
            if stderr:
                self._write_output(f"[red]{stderr.decode(errors='replace')}[/]")
            self._write_system(f"exit {proc.returncode}")
        except Exception as exc:
            self._write_system(f"[red]Terminal error:[/] {exc}")
        finally:
            self._running = False
