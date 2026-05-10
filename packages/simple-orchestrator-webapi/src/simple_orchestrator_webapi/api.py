from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, cast

import anyio
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from simple_orchestrator_core.api import (
    API_KEY_HEADER,
    AgentListResponse,
    AgentUpsertRequest,
    EnqueueRequest,
    EnqueueResponse,
    EventCreateRequest,
    EventListResponse,
    EventUpdateRequest,
    McpCreateRequest,
    McpListResponse,
    QueueDequeueResponse,
    QueueListResponse,
    QueueUpdateRequest,
    SessionCreateRequest,
    SessionListResponse,
    SessionUpdateRequest,
)
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.event_record import EventRecord
from simple_orchestrator_core.models.mcp_record import McpRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_core.models.worker_heartbeat import (
    HealthResponse,
    WorkerHeartbeat,
    WorkerHeartbeatStatus,
    WorkerType,
)
from simple_orchestrator_core.schedule import compute_next_run
from simple_orchestrator_core.settings import WebApiSettings
from simple_orchestrator_database import OrchestratorDB

from .logging_config import get_internal_logger, setup_logging
from .session_config_builder import build_session_config

logger = get_internal_logger(__name__)


@dataclass(frozen=True)
class WebApiState:
    settings: WebApiSettings
    db: OrchestratorDB


def _state(request: Request) -> WebApiState:
    return request.app.state.webapi


def _require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
) -> None:
    settings = _state(request).settings
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


router = APIRouter()


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    state = _state(request)
    records = await anyio.to_thread.run_sync(
        lambda: state.db.list_alive_workers(ttl_seconds=state.settings.heartbeat_ttl_seconds),
    )
    return HealthResponse(
        workers=[
            WorkerHeartbeatStatus(
                id=r.id,
                type=cast("WorkerType", r.type),
                name=r.name,
                last_heartbeat_at=r.last_heartbeat_at,
            )
            for r in records
        ],
    )


@router.post("/heartbeat", dependencies=[Depends(_require_api_key)])
async def send_heartbeat(request: Request, heartbeat: WorkerHeartbeat) -> dict[str, str]:
    db = _state(request).db
    await anyio.to_thread.run_sync(lambda: db.upsert_worker_heartbeat(heartbeat))
    return {"status": "ok"}


# ── agents ────────────────────────────────────────────────────────────────────


@router.get("/agents", response_model=AgentListResponse, dependencies=[Depends(_require_api_key)])
async def list_agents(request: Request) -> AgentListResponse:
    db = _state(request).db
    agents = await anyio.to_thread.run_sync(db.list_agents)
    return AgentListResponse(agents=agents)


@router.get("/agents/{agent_id}", response_model=AgentRecord, dependencies=[Depends(_require_api_key)])
async def get_agent(request: Request, agent_id: str) -> AgentRecord:
    db = _state(request).db
    agent = await anyio.to_thread.run_sync(lambda: db.get_agent(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/agents", response_model=AgentRecord, dependencies=[Depends(_require_api_key)])
async def upsert_agent(request: Request, req: AgentUpsertRequest) -> AgentRecord:
    db = _state(request).db
    return await anyio.to_thread.run_sync(lambda: db.upsert_agent(req))


@router.delete("/agents/{agent_id}", dependencies=[Depends(_require_api_key)])
async def delete_agent(request: Request, agent_id: str) -> dict[str, str]:
    db = _state(request).db
    deleted = await anyio.to_thread.run_sync(lambda: db.delete_agent(agent_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "ok"}


# ── queue ─────────────────────────────────────────────────────────────────────


@router.post("/queue", response_model=EnqueueResponse, dependencies=[Depends(_require_api_key)])
async def enqueue(request: Request, req: EnqueueRequest) -> EnqueueResponse:
    db = _state(request).db
    agent = await anyio.to_thread.run_sync(lambda: db.get_agent(req.agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
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


@router.get("/queue", response_model=QueueListResponse, dependencies=[Depends(_require_api_key)])
async def list_queue(request: Request, status: str | None = None, agent_id: str | None = None) -> QueueListResponse:
    db = _state(request).db
    items = await anyio.to_thread.run_sync(lambda: db.list_queue(status=status, agent_id=agent_id))
    return QueueListResponse(items=items)


@router.get("/queue/{item_id}", response_model=QueueItem, dependencies=[Depends(_require_api_key)])
async def get_queue_item(request: Request, item_id: str) -> QueueItem:
    db = _state(request).db
    item = await anyio.to_thread.run_sync(lambda: db.get_queue_item(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@router.patch("/queue/{item_id}", response_model=QueueItem, dependencies=[Depends(_require_api_key)])
async def update_queue_item(request: Request, item_id: str, req: QueueUpdateRequest) -> QueueItem:
    db = _state(request).db
    item = await anyio.to_thread.run_sync(lambda: db.update_queue_item_api(item_id, req))
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@router.post("/queue/{item_id}/cancel", dependencies=[Depends(_require_api_key)])
async def cancel_queue_item(request: Request, item_id: str) -> dict[str, str]:
    db = _state(request).db
    await anyio.to_thread.run_sync(lambda: db.cancel_queue_item(item_id))
    return {"status": "ok"}


@router.post("/queue/dequeue", response_model=QueueDequeueResponse, dependencies=[Depends(_require_api_key)])
async def dequeue_next(request: Request) -> QueueDequeueResponse:
    state = _state(request)
    db = state.db
    item = await anyio.to_thread.run_sync(db.dequeue_next)
    if not item:
        return Response(status_code=204)  # type: ignore[return-value]

    agent = await anyio.to_thread.run_sync(lambda: db.get_agent(item.agent_id))
    if not agent:
        await anyio.to_thread.run_sync(lambda: db.update_queue_item(item.id, status="failed"))
        raise HTTPException(status_code=500, detail="Dequeued item references missing agent")

    global_mcps = await anyio.to_thread.run_sync(lambda: db.list_mcps(is_global=True, enabled=True))
    session_config = build_session_config(agent=agent, item=item, global_mcps=global_mcps)
    return QueueDequeueResponse(
        item=item,
        vendor=agent.vendor,
        timeout_minutes=agent.task_timeout_minutes,
        session_config=session_config,
    )


# ── sessions ──────────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=SessionListResponse, dependencies=[Depends(_require_api_key)])
async def list_sessions(request: Request, vendor: str | None = None, status: str | None = None) -> SessionListResponse:
    db = _state(request).db
    sessions = await anyio.to_thread.run_sync(lambda: db.list_sessions(vendor=vendor, status=status))
    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}", response_model=SessionRecord, dependencies=[Depends(_require_api_key)])
async def get_session(request: Request, session_id: str) -> SessionRecord:
    db = _state(request).db
    record = await anyio.to_thread.run_sync(lambda: db.get_session(session_id))
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    return record


@router.post("/sessions", dependencies=[Depends(_require_api_key)])
async def create_session(request: Request, req: SessionCreateRequest) -> dict[str, str]:
    db = _state(request).db
    # Ensure nested SessionRecord is fully converted from Pydantic to SQLModel
    record = SessionRecord.model_validate(req.record.model_dump())
    await anyio.to_thread.run_sync(lambda: db.save_session(record))
    return {"status": "ok"}


@router.patch("/sessions/{session_id}", dependencies=[Depends(_require_api_key)])
async def update_session(request: Request, session_id: str, req: SessionUpdateRequest) -> dict[str, str]:
    db = _state(request).db
    await anyio.to_thread.run_sync(lambda: db.update_session_status(session_id, req))
    return {"status": "ok"}


# ── mcps ──────────────────────────────────────────────────────────────────────


@router.get("/mcps", response_model=McpListResponse, dependencies=[Depends(_require_api_key)])
async def list_mcps(
    request: Request,
    is_global: bool | None = None,  # noqa: FBT001
    enabled: bool | None = None,  # noqa: FBT001
) -> McpListResponse:
    db = _state(request).db
    mcps = await anyio.to_thread.run_sync(lambda: db.list_mcps(is_global=is_global, enabled=enabled))
    return McpListResponse(mcps=mcps)


@router.get("/mcps/{mcp_id}", response_model=McpRecord, dependencies=[Depends(_require_api_key)])
async def get_mcp(request: Request, mcp_id: str) -> McpRecord:
    db = _state(request).db
    mcp = await anyio.to_thread.run_sync(lambda: db.get_mcp(mcp_id))
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP not found")
    return mcp


@router.post("/mcps", response_model=McpRecord, dependencies=[Depends(_require_api_key)])
async def upsert_mcp(request: Request, req: McpCreateRequest) -> McpRecord:
    db = _state(request).db
    return await anyio.to_thread.run_sync(lambda: db.upsert_mcp(req))


@router.delete("/mcps/{mcp_id}", dependencies=[Depends(_require_api_key)])
async def delete_mcp(request: Request, mcp_id: str) -> dict[str, str]:
    db = _state(request).db
    deleted = await anyio.to_thread.run_sync(lambda: db.delete_mcp(mcp_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP not found")
    return {"status": "ok"}


# ── events ────────────────────────────────────────────────────────────────────


@router.get("/events", response_model=EventListResponse, dependencies=[Depends(_require_api_key)])
async def list_events(request: Request, enabled: bool | None = None) -> EventListResponse:  # noqa: FBT001
    db = _state(request).db
    events = await anyio.to_thread.run_sync(lambda: db.list_events(enabled=enabled))
    return EventListResponse(events=events)


@router.get("/events/{event_id}", response_model=EventRecord, dependencies=[Depends(_require_api_key)])
async def get_event(request: Request, event_id: str) -> EventRecord:
    db = _state(request).db
    event = await anyio.to_thread.run_sync(lambda: db.get_event(event_id))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/events", response_model=EventRecord, dependencies=[Depends(_require_api_key)])
async def create_event(request: Request, req: EventCreateRequest) -> EventRecord:
    db = _state(request).db
    agent = await anyio.to_thread.run_sync(lambda: db.get_agent(req.agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await anyio.to_thread.run_sync(lambda: db.create_event(req))


@router.patch("/events/{event_id}", response_model=EventRecord, dependencies=[Depends(_require_api_key)])
async def update_event(request: Request, event_id: str, req: EventUpdateRequest) -> EventRecord:
    db = _state(request).db
    event = await anyio.to_thread.run_sync(lambda: db.update_event(event_id, req))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/events/{event_id}", dependencies=[Depends(_require_api_key)])
async def delete_event(request: Request, event_id: str) -> dict[str, str]:
    db = _state(request).db
    deleted = await anyio.to_thread.run_sync(lambda: db.delete_event(event_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"status": "ok"}


@router.post("/events/{event_id}/trigger", response_model=EnqueueResponse, dependencies=[Depends(_require_api_key)])
async def trigger_event(request: Request, event_id: str) -> EnqueueResponse:
    db = _state(request).db
    event = await anyio.to_thread.run_sync(lambda: db.get_event(event_id))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    agent = await anyio.to_thread.run_sync(lambda: db.get_agent(event.agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent referenced by event not found")
    item = await anyio.to_thread.run_sync(
        lambda: db.enqueue(agent_id=event.agent_id, prompt=event.prompt, workdir=event.workdir),
    )
    next_run = compute_next_run(
        event.schedule_type,
        interval_minutes=event.interval_minutes,
        cron_expression=event.cron_expression,
    )
    await anyio.to_thread.run_sync(lambda: db.update_next_run(event_id, next_run))
    return EnqueueResponse(item=item)


def create_app() -> FastAPI:
    settings = WebApiSettings()
    setup_logging(settings.logs_dir, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        db = OrchestratorDB(settings.db_path)
        app.state.webapi = WebApiState(settings=settings, db=db)
        logger.info(
            "Web API started http=%s:%d db=%s",
            settings.webapi_host,
            settings.webapi_port,
            settings.db_path,
        )
        try:
            yield
        finally:
            db.close()

    app = FastAPI(title="Simple Orchestrator Web API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
