from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, cast

from simple_orchestrator_core.api import (
    AgentUpsertRequest,
    EnqueueRequest,
    EventCreateRequest,
    EventUpdateRequest,
    McpCreateRequest,
)
from simple_orchestrator_core.interfaces import IOrchestratorClient
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.event_record import EventRecord
from simple_orchestrator_core.models.mcp_record import McpRecord
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Select, TextArea
from ulid import ULID


@dataclass(frozen=True)
class _EnqueueResult:
    agent_id: str
    prompt: str
    workdir: str | None


@dataclass(frozen=True)
class _AgentUpsertResult:
    req: AgentUpsertRequest


@dataclass(frozen=True)
class _McpUpsertResult:
    req: McpCreateRequest


@dataclass(frozen=True)
class _EventMutationResult:
    kind: Literal["create", "update"]
    event_id: str | None
    create_req: EventCreateRequest | None
    update_req: EventUpdateRequest | None


class EnqueueModal(ModalScreen[_EnqueueResult | None]):
    DEFAULT_CSS = """
    EnqueueModal {
        align: center middle;
    }
    EnqueueModal > Vertical {
        width: 96%;
        max-width: 140;
        height: auto;
        max-height: 95%;
        border: round #7aa2f7;
        border-title: "Enqueue";
        padding: 1 2;
        background: #24283b;
    }
    EnqueueModal TextArea {
        height: 12;
    }
    """

    def __init__(self, agents: list[AgentRecord]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        options = [(f"{a.name} ({a.id})", a.id) for a in self._agents]
        with Vertical():
            if options:
                yield Select(options, prompt="Select agent", id="agent_select")
            else:
                yield Input(placeholder="agent_id", id="agent_id")
            yield Input(placeholder="git remote (optional)", id="workdir")
            yield TextArea("", id="prompt")
            with Horizontal():
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Enqueue", variant="primary", id="enqueue")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#enqueue")
    def _enqueue(self) -> None:
        agent_id = self._get_agent_id()
        workdir_raw = self.query_one("#workdir", Input).value.strip()
        prompt = self.query_one("#prompt", TextArea).text.strip()
        if not agent_id or not prompt:
            return
        self.dismiss(_EnqueueResult(agent_id=agent_id, prompt=prompt, workdir=workdir_raw or None))

    def _get_agent_id(self) -> str:
        try:
            sel = self.query_one("#agent_select", Select)
            v = sel.value
            return str(v) if v and v is not Select.BLANK else ""
        except Exception:  # noqa: S110
            pass
        try:
            return self.query_one("#agent_id", Input).value.strip()
        except Exception:
            return ""


class ConfirmModal(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        width: 90%;
        max-width: 90;
        height: auto;
        border: round #7aa2f7;
        border-title: "Confirm";
        padding: 1 2;
        background: #24283b;
    }
    ConfirmModal Label {
        margin: 0 0 1 0;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._message)
            with Horizontal():
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("OK", variant="primary", id="ok")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(result=False)

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(result=True)


class AgentEditorModal(ModalScreen[_AgentUpsertResult | None]):
    DEFAULT_CSS = """
    AgentEditorModal {
        align: center middle;
    }
    AgentEditorModal > Vertical {
        width: 96%;
        max-width: 140;
        height: auto;
        max-height: 95%;
        border: round #7aa2f7;
        border-title: "Agent";
        padding: 1 2;
        background: #24283b;
    }
    AgentEditorModal .row {
        height: auto;
        margin: 0 0 1 0;
    }
    AgentEditorModal TextArea {
        height: 8;
    }
    """

    def __init__(self, agent: AgentRecord | None) -> None:
        super().__init__()
        self._agent = agent

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Create" if self._agent is None else f"Edit: {self._agent.name}")
            with Horizontal(classes="row"):
                yield Input(value=self._agent.id if self._agent else str(ULID()), placeholder="id", id="id")
                yield Input(value=self._agent.name if self._agent else "", placeholder="name", id="name")
            with Horizontal(classes="row"):
                yield Input(value=self._agent.vendor if self._agent else "", placeholder="vendor", id="vendor")
                yield Input(
                    value=self._agent.model or "" if self._agent else "",
                    placeholder="model (optional)",
                    id="model",
                )
            with Horizontal(classes="row"):
                yield Input(
                    value=self._agent.nickname or "" if self._agent else "",
                    placeholder="nickname (optional)",
                    id="nickname",
                )
            yield Input(
                value=str(self._agent.task_timeout_minutes) if self._agent and self._agent.task_timeout_minutes else "",
                placeholder="task_timeout_minutes (optional)",
                id="timeout",
                classes="row",
            )
            yield Label("prompt")
            yield TextArea(self._agent.prompt if self._agent else "", id="prompt")
            yield Label("mcp_servers (JSON dict)")
            yield TextArea(
                json.dumps(self._agent.mcp_servers if self._agent else {}, indent=2, sort_keys=True),
                id="mcp_servers",
            )
            yield Label("skills (JSON list)")
            yield TextArea(json.dumps(self._agent.skills if self._agent else [], indent=2), id="skills")
            yield Label("skill_globs (JSON list[str])")
            yield TextArea(json.dumps(self._agent.skill_globs if self._agent else [], indent=2), id="skill_globs")
            with Horizontal():
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Save", variant="primary", id="save")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        agent_id = self.query_one("#id", Input).value.strip()
        name = self.query_one("#name", Input).value.strip()
        vendor = self.query_one("#vendor", Input).value.strip()
        if not agent_id or not name or not vendor:
            return

        model = self.query_one("#model", Input).value.strip() or None
        nickname = self.query_one("#nickname", Input).value.strip() or None
        timeout_raw = self.query_one("#timeout", Input).value.strip()
        timeout_minutes = float(timeout_raw) if timeout_raw else None

        prompt = self.query_one("#prompt", TextArea).text.strip()
        if not prompt:
            return

        mcp_servers = _parse_json(self.query_one("#mcp_servers", TextArea).text, default={})
        skills = _parse_json(self.query_one("#skills", TextArea).text, default=[])
        skill_globs = _parse_json(self.query_one("#skill_globs", TextArea).text, default=[])

        if not isinstance(mcp_servers, dict) or not isinstance(skills, list) or not isinstance(skill_globs, list):
            return

        req = AgentUpsertRequest(
            id=agent_id,
            name=name,
            nickname=nickname,
            vendor=vendor,
            model=model,
            task_timeout_minutes=timeout_minutes,
            prompt=prompt,
            mcp_servers=mcp_servers,
            skills=skills,
            skill_globs=cast("list[str]", skill_globs),
        )
        self.dismiss(_AgentUpsertResult(req=req))


class McpEditorModal(ModalScreen[_McpUpsertResult | None]):
    DEFAULT_CSS = """
    McpEditorModal {
        align: center middle;
    }
    McpEditorModal > Vertical {
        width: 96%;
        max-width: 140;
        height: auto;
        max-height: 95%;
        border: round #7aa2f7;
        border-title: "MCP";
        padding: 1 2;
        background: #24283b;
    }
    McpEditorModal .row {
        height: auto;
        margin: 0 0 1 0;
    }
    McpEditorModal TextArea {
        height: 6;
    }
    """

    def __init__(self, mcp: McpRecord | None) -> None:
        super().__init__()
        self._mcp = mcp

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Create" if self._mcp is None else f"Edit: {self._mcp.name}")
            with Horizontal(classes="row"):
                yield Input(value=self._mcp.id if self._mcp else str(ULID()), placeholder="id", id="id")
                yield Input(value=self._mcp.name if self._mcp else "", placeholder="name", id="name")
            yield Select(
                [("stdio", "stdio"), ("sse", "sse"), ("http", "http")],
                value=self._mcp.type if self._mcp else "stdio",
                id="type",
            )
            with Horizontal(classes="row"):
                yield Input(
                    value=self._mcp.command or "" if self._mcp else "",
                    placeholder="command (stdio)",
                    id="command",
                )
                yield Input(value=self._mcp.url or "" if self._mcp else "", placeholder="url (sse/http)", id="url")
            yield Label("args (JSON list) / env (JSON dict)")
            with Horizontal(classes="row"):
                yield TextArea(json.dumps(self._mcp.args if self._mcp else [], indent=2), id="args")
                yield TextArea(
                    json.dumps(self._mcp.env if self._mcp else {}, indent=2, sort_keys=True),
                    id="env",
                )
            yield Label("headers (JSON dict)")
            yield TextArea(
                json.dumps(self._mcp.headers if self._mcp else {}, indent=2, sort_keys=True),
                id="headers",
            )
            with Horizontal(classes="row"):
                yield Select(
                    [("global", "global"), ("agent-only", "agent-only")],
                    value="global" if (self._mcp.is_global if self._mcp else True) else "agent-only",
                    id="is_global",
                )
                yield Select(
                    [("enabled", "enabled"), ("disabled", "disabled")],
                    value="enabled" if (self._mcp.enabled if self._mcp else True) else "disabled",
                    id="enabled",
                )
            with Horizontal():
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Save", variant="primary", id="save")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        mcp_id = self.query_one("#id", Input).value.strip()
        name = self.query_one("#name", Input).value.strip()
        if not mcp_id or not name:
            return

        type_sel = self.query_one("#type", Select)
        raw_type = str(type_sel.value) if type_sel.value and type_sel.value is not Select.BLANK else ""
        if raw_type not in {"stdio", "sse", "http"}:
            return

        command = self.query_one("#command", Input).value.strip() or None
        url = self.query_one("#url", Input).value.strip() or None

        args = _parse_json(self.query_one("#args", TextArea).text, default=[])
        env = _parse_json(self.query_one("#env", TextArea).text, default={})
        headers = _parse_json(self.query_one("#headers", TextArea).text, default={})
        if not isinstance(args, list) or not isinstance(env, dict) or not isinstance(headers, dict):
            return

        is_global = self.query_one("#is_global", Select).value == "global"
        enabled = self.query_one("#enabled", Select).value == "enabled"

        req = McpCreateRequest(
            id=mcp_id,
            name=name,
            type=cast('Literal["stdio", "sse", "http"]', raw_type),
            command=command,
            args=cast("list[str]", args),
            env=cast("dict[str, str]", env),
            url=url,
            headers=cast("dict[str, str]", headers),
            is_global=is_global,
            enabled=enabled,
        )
        self.dismiss(_McpUpsertResult(req=req))


class EventEditorModal(ModalScreen[_EventMutationResult | None]):
    DEFAULT_CSS = """
    EventEditorModal {
        align: center middle;
    }
    EventEditorModal > Vertical {
        width: 96%;
        max-width: 140;
        height: auto;
        max-height: 95%;
        border: round #7aa2f7;
        border-title: "Scheduler";
        padding: 1 2;
        background: #24283b;
    }
    EventEditorModal .row {
        height: auto;
        margin: 0 0 1 0;
    }
    EventEditorModal TextArea {
        height: 8;
    }
    """

    def __init__(self, event: EventRecord | None, *, agents: list[AgentRecord]) -> None:
        super().__init__()
        self._event = event
        self._agents = agents

    def compose(self) -> ComposeResult:
        agent_options = [(f"{a.name} ({a.id})", a.id) for a in self._agents]
        with Vertical():
            yield Label("Create" if self._event is None else f"Edit: {self._event.name}")
            yield Input(value=self._event.name if self._event else "", placeholder="name", id="name", classes="row")
            if agent_options:
                yield Select(
                    agent_options,
                    value=self._event.agent_id if self._event else Select.BLANK,
                    prompt="Select agent",
                    id="agent_id",
                    classes="row",
                )
            else:
                yield Input(
                    value=self._event.agent_id if self._event else "",
                    placeholder="agent_id",
                    id="agent_id_raw",
                    classes="row",
                )
            yield Input(
                value=self._event.workdir or "" if self._event else "",
                placeholder="git remote (optional)",
                id="workdir",
                classes="row",
            )
            yield Label("prompt")
            yield TextArea(self._event.prompt if self._event else "", id="prompt")
            yield Select(
                [("interval", "interval"), ("cron", "cron")],
                value=self._event.schedule_type if self._event else "interval",
                id="schedule_type",
                classes="row",
            )
            with Horizontal(classes="row"):
                yield Input(
                    value=str(self._event.interval_minutes) if self._event and self._event.interval_minutes else "",
                    placeholder="interval_minutes (interval)",
                    id="interval",
                )
                yield Input(
                    value=self._event.cron_expression or "" if self._event else "",
                    placeholder="cron_expression (cron)",
                    id="cron",
                )
            yield Select(
                [("enabled", "enabled"), ("disabled", "disabled")],
                value="enabled" if (self._event.enabled if self._event else True) else "disabled",
                id="enabled",
                classes="row",
            )
            with Horizontal():
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Save", variant="primary", id="save")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        prompt = self.query_one("#prompt", TextArea).text.strip()
        if not name or not prompt:
            return

        workdir = self.query_one("#workdir", Input).value.strip() or None
        schedule_type = cast("str", self.query_one("#schedule_type", Select).value)
        enabled = self.query_one("#enabled", Select).value == "enabled"

        interval_raw = self.query_one("#interval", Input).value.strip()
        cron_expression = self.query_one("#cron", Input).value.strip() or None
        interval_minutes = float(interval_raw) if interval_raw else None

        agent_id = ""
        try:
            v = self.query_one("#agent_id", Select).value
            agent_id = str(v) if v and v is not Select.BLANK else ""
        except Exception:
            agent_id = self.query_one("#agent_id_raw", Input).value.strip()
        if not agent_id:
            return

        if self._event is None:
            create_req = EventCreateRequest(
                name=name,
                agent_id=agent_id,
                prompt=prompt,
                workdir=workdir,
                schedule_type=cast('Literal["interval", "cron"]', schedule_type),
                interval_minutes=interval_minutes,
                cron_expression=cron_expression,
                enabled=enabled,
            )
            self.dismiss(
                _EventMutationResult(
                    kind="create",
                    event_id=None,
                    create_req=create_req,
                    update_req=None,
                ),
            )
            return

        update_req = EventUpdateRequest(
            name=name,
            prompt=prompt,
            workdir=workdir,
            schedule_type=cast('Literal["interval", "cron"]', schedule_type),
            interval_minutes=interval_minutes,
            cron_expression=cron_expression,
            enabled=enabled,
        )
        self.dismiss(
            _EventMutationResult(
                kind="update",
                event_id=self._event.id,
                create_req=None,
                update_req=update_req,
            ),
        )


class OrchestratorTUI(App[None]):
    TITLE = "Simple Orchestrator"

    CSS = """
    Screen {
        background: #1a1b26;
        color: #c0caf5;
    }

    Header, Footer {
        background: #16161e;
        color: #c0caf5;
    }

    #body { height: 1fr; }

    #sidebar {
        width: 46;
        height: 100%;
        padding: 0;
        margin: 0;
    }

    #main { height: 100%; }

    .panel {
        background: #24283b;
        border: round #7aa2f7;
        padding: 1 2;
        margin: 1;
    }

    #agents_panel { border-title: "Agents"; }
    #mcps_panel { border-title: "MCP"; }
    #events_panel { border-title: "Scheduler"; }
    #logs_panel { border-title: "Logs"; }

    #kanban {
        height: 1fr;
        margin: 1;
    }

    .kanban_col {
        background: #24283b;
        border: round #7aa2f7;
        padding: 1 2;
        margin: 0 1;
    }

    #pending_col { border-title: "Pendente"; }
    #running_col { border-title: "Em execução"; }
    #done_col { border-title: "Concluído (recente)"; }

    #logs_panel {
        height: 14;
        margin: 1;
    }

    .actions {
        height: auto;
        margin-top: 1;
    }

    DataTable { background: transparent; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "enqueue", "Enqueue"),
    ]

    def __init__(
        self,
        client: IOrchestratorClient,
        *,
        background_worker: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._background_worker = background_worker
        self._agents: list[AgentRecord] = []
        self._events: list[EventRecord] = []
        self._mcps: list[McpRecord] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                with Vertical(id="agents_panel", classes="panel"):
                    yield DataTable(id="agents")
                    with Horizontal(classes="actions"):
                        yield Button("Add", id="agent_add", variant="primary")
                        yield Button("Edit", id="agent_edit")
                        yield Button("Delete", id="agent_delete", variant="error")
                with Vertical(id="mcps_panel", classes="panel"):
                    yield DataTable(id="mcps")
                    with Horizontal(classes="actions"):
                        yield Button("Add", id="mcp_add", variant="primary")
                        yield Button("Edit", id="mcp_edit")
                        yield Button("Delete", id="mcp_delete", variant="error")
                with Vertical(id="events_panel", classes="panel"):
                    yield DataTable(id="events")
                    with Horizontal(classes="actions"):
                        yield Button("Add", id="event_add", variant="primary")
                        yield Button("Edit", id="event_edit")
                        yield Button("Delete", id="event_delete", variant="error")
                        yield Button("Trigger", id="event_trigger")
            with Vertical(id="main"):
                with Horizontal(id="kanban"):
                    with Vertical(id="pending_col", classes="kanban_col"):
                        yield DataTable(id="queue_pending")
                    with Vertical(id="running_col", classes="kanban_col"):
                        yield DataTable(id="queue_running")
                    with Vertical(id="done_col", classes="kanban_col"):
                        yield DataTable(id="queue_done")
                with Vertical(id="logs_panel", classes="panel"):
                    yield RichLog(id="logs", wrap=True, highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        agents_table = self.query_one("#agents", DataTable)
        agents_table.cursor_type = "row"
        agents_table.add_column("id")
        agents_table.add_column("name")
        agents_table.add_column("vendor/model")

        mcps_table = self.query_one("#mcps", DataTable)
        mcps_table.cursor_type = "row"
        mcps_table.add_column("id")
        mcps_table.add_column("name")
        mcps_table.add_column("type")
        mcps_table.add_column("enabled")

        events_table = self.query_one("#events", DataTable)
        events_table.cursor_type = "row"
        events_table.add_column("id")
        events_table.add_column("name")
        events_table.add_column("schedule")
        events_table.add_column("enabled")

        pending_table = self.query_one("#queue_pending", DataTable)
        pending_table.cursor_type = "row"
        pending_table.add_column("id")
        pending_table.add_column("agent")
        pending_table.add_column("created")
        pending_table.add_column("prompt")

        running_table = self.query_one("#queue_running", DataTable)
        running_table.cursor_type = "row"
        running_table.add_column("id")
        running_table.add_column("agent")
        running_table.add_column("started")
        running_table.add_column("prompt")

        done_table = self.query_one("#queue_done", DataTable)
        done_table.cursor_type = "row"
        done_table.add_column("id")
        done_table.add_column("agent")
        done_table.add_column("status")
        done_table.add_column("ended")
        done_table.add_column("note")

        if self._background_worker is not None:
            self.run_worker(self._background_worker, exclusive=False)

        self.set_interval(2.0, self.action_refresh)
        self.action_refresh()
        self._log("Ready.")

    def action_enqueue(self) -> None:
        async def handle(result: _EnqueueResult | None) -> None:
            if not result:
                return
            await self._enqueue_async(result)

        self.push_screen(EnqueueModal(self._agents), handle)

    def action_refresh(self) -> None:
        self._refresh_async()

    @work(exclusive=True)
    async def _refresh_async(self) -> None:
        await self._refresh_agents()
        await self._refresh_mcps()
        await self._refresh_events()
        await self._refresh_queue()

    async def _refresh_queue(self) -> None:
        try:
            items = await self._client.list_queue()
        except Exception as e:
            self._log_error(f"queue refresh failed: {e}")
            return

        pending = [it for it in items if it.status == "pending"]
        running = [it for it in items if it.status == "running"]
        done = [it for it in items if it.status in {"completed", "failed", "cancelled", "killed"}]
        done.sort(
            key=lambda it: _as_sortable_dt(it.ended_at) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        done = done[:25]

        pending_table = self.query_one("#queue_pending", DataTable)
        pending_table.clear()
        for it in pending:
            pending_table.add_row(
                it.id,
                it.agent_id,
                _fmt_dt(it.created_at),
                _short(it.prompt),
                key=it.id,
            )

        running_table = self.query_one("#queue_running", DataTable)
        running_table.clear()
        for it in running:
            running_table.add_row(
                it.id,
                it.agent_id,
                _fmt_dt(it.started_at),
                _short(it.prompt),
                key=it.id,
            )

        done_table = self.query_one("#queue_done", DataTable)
        done_table.clear()
        for it in done:
            done_table.add_row(
                it.id,
                it.agent_id,
                it.status,
                _fmt_dt(it.ended_at),
                _short(it.note or ""),
                key=it.id,
            )

    async def _refresh_agents(self) -> None:
        table = self.query_one("#agents", DataTable)
        try:
            self._agents = await self._client.list_agents()
        except Exception as e:
            table.clear()
            table.add_row("error", str(e), "", key="error")
            self._log_error(f"agents refresh failed: {e}")
            return
        table.clear()
        for a in self._agents:
            table.add_row(a.id, a.name, f"{a.vendor}/{a.model or ''}".rstrip("/"), key=a.id)

    async def _refresh_mcps(self) -> None:
        table = self.query_one("#mcps", DataTable)
        try:
            self._mcps = await self._client.list_mcps()
        except Exception as e:
            table.clear()
            table.add_row("error", str(e), "", "", key="error")
            self._log_error(f"mcps refresh failed: {e}")
            return
        table.clear()
        for m in self._mcps:
            table.add_row(m.id, m.name, m.type, "yes" if m.enabled else "no", key=m.id)

    async def _refresh_events(self) -> None:
        table = self.query_one("#events", DataTable)
        try:
            self._events = await self._client.list_events()
        except Exception as e:
            table.clear()
            table.add_row("error", str(e), "", "", key="error")
            self._log_error(f"events refresh failed: {e}")
            return
        table.clear()
        for ev in self._events:
            sched = f"every {ev.interval_minutes}m" if ev.schedule_type == "interval" else f"cron: {ev.cron_expression}"
            table.add_row(ev.id, ev.name, sched, "yes" if ev.enabled else "no", key=ev.id)

    async def _enqueue_async(self, result: _EnqueueResult) -> None:
        self._log(f"Enqueue agent_id={result.agent_id}")
        await self._client.enqueue(
            EnqueueRequest(agent_id=result.agent_id, prompt=result.prompt, workdir=result.workdir),
        )
        self.action_refresh()

    # ── sidebar actions ──────────────────────────────────────────────────────

    @on(Button.Pressed, "#agent_add")
    def _agent_add(self) -> None:
        async def handle(res: _AgentUpsertResult | None) -> None:
            if res is None:
                return
            self._upsert_agent(res.req)

        self.push_screen(AgentEditorModal(None), handle)

    @on(Button.Pressed, "#agent_edit")
    def _agent_edit(self) -> None:
        agent_id = self._selected_row_key("#agents")
        if not agent_id:
            return

        async def handle(res: _AgentUpsertResult | None) -> None:
            if res is None:
                return
            self._upsert_agent(res.req)

        self._edit_agent_async(agent_id, handle)

    @work(exclusive=True)
    async def _edit_agent_async(
        self,
        agent_id: str,
        done: Callable[[_AgentUpsertResult | None], Coroutine[Any, Any, None]],
    ) -> None:
        try:
            agent = await self._client.get_agent(agent_id)
        except Exception as e:
            self._log_error(f"get_agent failed: {e}")
            return
        self.push_screen(AgentEditorModal(agent), done)

    @on(Button.Pressed, "#agent_delete")
    def _agent_delete(self) -> None:
        agent_id = self._selected_row_key("#agents")
        if not agent_id:
            return

        async def handle(result: object) -> None:
            if result is not True:
                return
            try:
                await self._client.delete_agent(agent_id)
                self._log(f"Deleted agent_id={agent_id}")
            except Exception as e:
                self._log_error(f"delete_agent failed: {e}")
            self.action_refresh()

        self.push_screen(ConfirmModal(f"Delete agent {agent_id}?"), handle)

    @work(exclusive=True)
    async def _upsert_agent(self, req: AgentUpsertRequest) -> None:
        try:
            await self._client.upsert_agent(req)
            self._log(f"Saved agent_id={req.id}")
        except Exception as e:
            self._log_error(f"upsert_agent failed: {e}")
        self.action_refresh()

    @on(Button.Pressed, "#mcp_add")
    def _mcp_add(self) -> None:
        async def handle(res: _McpUpsertResult | None) -> None:
            if res is None:
                return
            self._upsert_mcp(res.req)

        self.push_screen(McpEditorModal(None), handle)

    @on(Button.Pressed, "#mcp_edit")
    def _mcp_edit(self) -> None:
        mcp_id = self._selected_row_key("#mcps")
        if not mcp_id:
            return

        async def handle(res: _McpUpsertResult | None) -> None:
            if res is None:
                return
            self._upsert_mcp(res.req)

        self._edit_mcp_async(mcp_id, handle)

    @work(exclusive=True)
    async def _edit_mcp_async(
        self,
        mcp_id: str,
        done: Callable[[_McpUpsertResult | None], Coroutine[Any, Any, None]],
    ) -> None:
        try:
            mcp = await self._client.get_mcp(mcp_id)
        except Exception as e:
            self._log_error(f"get_mcp failed: {e}")
            return
        self.push_screen(McpEditorModal(mcp), done)

    @on(Button.Pressed, "#mcp_delete")
    def _mcp_delete(self) -> None:
        mcp_id = self._selected_row_key("#mcps")
        if not mcp_id:
            return

        async def handle(result: object) -> None:
            if result is not True:
                return
            try:
                await self._client.delete_mcp(mcp_id)
                self._log(f"Deleted mcp_id={mcp_id}")
            except Exception as e:
                self._log_error(f"delete_mcp failed: {e}")
            self.action_refresh()

        self.push_screen(ConfirmModal(f"Delete MCP {mcp_id}?"), handle)

    @work(exclusive=True)
    async def _upsert_mcp(self, req: McpCreateRequest) -> None:
        try:
            await self._client.upsert_mcp(req)
            self._log(f"Saved mcp_id={req.id}")
        except Exception as e:
            self._log_error(f"upsert_mcp failed: {e}")
        self.action_refresh()

    @on(Button.Pressed, "#event_add")
    def _event_add(self) -> None:
        async def handle(res: _EventMutationResult | None) -> None:
            if res is None:
                return
            self._mutate_event(res)

        self.push_screen(EventEditorModal(None, agents=self._agents), handle)

    @on(Button.Pressed, "#event_edit")
    def _event_edit(self) -> None:
        event_id = self._selected_row_key("#events")
        if not event_id:
            return

        async def handle(res: _EventMutationResult | None) -> None:
            if res is None:
                return
            self._mutate_event(res)

        self._edit_event_async(event_id, handle)

    @work(exclusive=True)
    async def _edit_event_async(
        self,
        event_id: str,
        done: Callable[[_EventMutationResult | None], Coroutine[Any, Any, None]],
    ) -> None:
        try:
            ev = await self._client.get_event(event_id)
        except Exception as e:
            self._log_error(f"get_event failed: {e}")
            return
        self.push_screen(EventEditorModal(ev, agents=self._agents), done)

    @on(Button.Pressed, "#event_delete")
    def _event_delete(self) -> None:
        event_id = self._selected_row_key("#events")
        if not event_id:
            return

        async def handle(result: object) -> None:
            if result is not True:
                return
            try:
                await self._client.delete_event(event_id)
                self._log(f"Deleted event_id={event_id}")
            except Exception as e:
                self._log_error(f"delete_event failed: {e}")
            self.action_refresh()

        self.push_screen(ConfirmModal(f"Delete event {event_id}?"), handle)

    @on(Button.Pressed, "#event_trigger")
    def _event_trigger(self) -> None:
        event_id = self._selected_row_key("#events")
        if not event_id:
            return
        self._trigger_event_async(event_id)

    @work(exclusive=True)
    async def _trigger_event_async(self, event_id: str) -> None:
        try:
            item = await self._client.trigger_event(event_id)
            self._log(f"Triggered event_id={event_id} -> queued item_id={item.id}")
        except Exception as e:
            self._log_error(f"trigger_event failed: {e}")
        self.action_refresh()

    @work(exclusive=True)
    async def _mutate_event(self, res: _EventMutationResult) -> None:
        try:
            if res.kind == "create" and res.create_req is not None:
                created = await self._client.create_event(res.create_req)
                self._log(f"Created event_id={created.id}")
            elif res.kind == "update" and res.event_id and res.update_req is not None:
                await self._client.update_event(res.event_id, res.update_req)
                self._log(f"Updated event_id={res.event_id}")
        except Exception as e:
            self._log_error(f"event mutation failed: {e}")
        self.action_refresh()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _selected_row_key(self, selector: str) -> str:
        table = self.query_one(selector, DataTable)
        if table.row_count == 0 or table.cursor_row < 0:
            return ""
        try:
            row = table.get_row_at(table.cursor_row)
        except Exception:
            return ""
        if not row:
            return ""
        return str(row[0]).strip()

    def _log(self, message: str) -> None:
        self.query_one("#logs", RichLog).write(message)

    def _log_error(self, message: str) -> None:
        self.query_one("#logs", RichLog).write(f"[bold #f7768e]error:[/] {message}")


def _fmt_dt(raw: object) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw
    if isinstance(raw, datetime):
        return raw.strftime("%Y-%m-%d %H:%M:%S")
    return str(raw)


def _as_sortable_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
        except ValueError:
            return None
    return None


def _short(text: str, *, max_len: int = 48) -> str:
    raw = " ".join(text.split())
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1] + "…"


def _parse_json(raw: str, *, default: object) -> object:
    raw = raw.strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def main() -> None:
    from simple_orchestrator_api_client import OrchestratorApiClient  # noqa: PLC0415
    from simple_orchestrator_core.settings import TuiSettings  # noqa: PLC0415

    settings = TuiSettings()
    OrchestratorTUI(client=OrchestratorApiClient(settings.api_url, api_key=settings.api_key)).run()
