from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.logging_config import get_internal_logger, setup_logging
from simple_orchestrator.models.agent_record import AgentRecord
from simple_orchestrator.models.queue_item import QueueItem
from simple_orchestrator.models.session import SessionRecord
from simple_orchestrator.queue_runner import QueueRunner
from simple_orchestrator.settings import AgentSettings, OrchestratorSettings
from simple_orchestrator.vendors import ClaudeCodeVendor, GithubCopilotVendor, OpenCodeVendor

logger = get_internal_logger(__name__)


@dataclass(frozen=True)
class WorkerState:
    settings: OrchestratorSettings
    db: OrchestratorDB
    vendors: dict[str, Any]
    runner: QueueRunner


class EnqueueRequest(BaseModel):
    agent_id: str
    prompt: str
    workdir: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    item_id: str | None = None


class EnqueueResponse(BaseModel):
    item: QueueItem


class QueueListResponse(BaseModel):
    items: list[QueueItem]


class AgentListResponse(BaseModel):
    agents: list[AgentRecord]


class SessionListResponse(BaseModel):
    sessions: list[SessionRecord]


def _agent_to_record(agent_id: str, agent_s: AgentSettings) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        name=agent_s.name,
        nickname=agent_s.nickname,
        prompt=agent_s.resolve_prompt(),
        model=agent_s.model,
        vendor=agent_s.vendor or "unknown",
        workdir=agent_s.workdir,
        created_at=datetime.now(UTC),
    )


def _build_vendors(db: OrchestratorDB) -> dict[str, Any]:
    return {
        "claude_code": ClaudeCodeVendor(db),
        "opencode": OpenCodeVendor(db),
        "github_copilot": GithubCopilotVendor(db),
    }


def _state(request: Request) -> WorkerState:
    return request.app.state.worker


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(request: Request) -> AgentListResponse:
    settings = _state(request).settings
    agents = [_agent_to_record(agent_id, agent_s) for agent_id, agent_s in settings.agents.items() if agent_s.vendor]
    return AgentListResponse(agents=agents)


@router.post("/queue", response_model=EnqueueResponse)
async def enqueue(request: Request, req: EnqueueRequest) -> EnqueueResponse:
    db = _state(request).db
    item = await anyio.to_thread.run_sync(
        lambda: db.enqueue(
            agent_id=req.agent_id,
            prompt=req.prompt,
            workdir=req.workdir,
            depends_on=req.depends_on,
            item_id=req.item_id,
        ),
    )
    return EnqueueResponse(item=item)


@router.get("/queue", response_model=QueueListResponse)
async def list_queue(request: Request, status: str | None = None, agent_id: str | None = None) -> QueueListResponse:
    db = _state(request).db
    items = await anyio.to_thread.run_sync(lambda: db.list_queue(status=status, agent_id=agent_id))
    return QueueListResponse(items=items)


@router.get("/queue/{item_id}", response_model=QueueItem)
async def get_queue_item(request: Request, item_id: str) -> QueueItem:
    db = _state(request).db
    item = await anyio.to_thread.run_sync(lambda: db.get_queue_item(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@router.post("/queue/{item_id}/cancel")
async def cancel_queue_item(request: Request, item_id: str) -> dict[str, str]:
    db = _state(request).db
    await anyio.to_thread.run_sync(lambda: db.cancel_queue_item(item_id))
    return {"status": "ok"}


@router.post("/queue/{item_id}/kill")
async def kill_queue_item(request: Request, item_id: str) -> dict[str, str]:
    state = _state(request)
    item = await anyio.to_thread.run_sync(lambda: state.db.get_queue_item(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    if item.status != "running":
        raise HTTPException(status_code=409, detail=f"Queue item is not running (status={item.status!r})")

    cancelled = await state.runner.kill_queue_item(item_id)

    agent_s = state.settings.agents.get(item.agent_id)
    if item.session_id and agent_s and agent_s.vendor:
        vendor = state.vendors.get(agent_s.vendor)
        if vendor is not None:
            await vendor.kill(item.session_id)

    if not cancelled and not item.session_id:
        raise HTTPException(status_code=409, detail="No active task handle for item (worker restart?)")

    return {"status": "ok"}


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request, vendor: str | None = None, status: str | None = None) -> SessionListResponse:
    db = _state(request).db
    sessions = await anyio.to_thread.run_sync(lambda: db.list_sessions(vendor=vendor, status=status))
    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}", response_model=SessionRecord)
async def get_session(request: Request, session_id: str) -> SessionRecord:
    db = _state(request).db
    record = await anyio.to_thread.run_sync(lambda: db.get(session_id))
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    return record


def create_app() -> FastAPI:
    settings = OrchestratorSettings()
    setup_logging(settings.logs_dir, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        db = OrchestratorDB(settings.db_path)
        vendors = _build_vendors(db)
        runner = QueueRunner(db, vendors, settings=settings)

        async with anyio.create_task_group() as tg:
            tg.start_soon(runner.start)
            app.state.worker = WorkerState(settings=settings, db=db, vendors=vendors, runner=runner)
            logger.info(
                "Worker started api=%s:%d db=%s max_active_sessions=%d",
                settings.api_host,
                settings.api_port,
                settings.db_path,
                settings.max_active_sessions,
            )
            yield
            runner.stop()

        db.close()

    app = FastAPI(title="Simple Orchestrator Worker", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
