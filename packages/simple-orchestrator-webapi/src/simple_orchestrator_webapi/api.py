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
    QueueDequeueResponse,
    QueueListResponse,
    QueueUpdateRequest,
    SessionCreateRequest,
    SessionListResponse,
    SessionUpdateRequest,
)
from simple_orchestrator_core.models.agent_record import AgentRecord
from simple_orchestrator_core.models.queue_item import QueueItem
from simple_orchestrator_core.models.session import SessionRecord
from simple_orchestrator_core.models.worker_heartbeat import (
    HealthResponse,
    WorkerHeartbeat,
    WorkerHeartbeatStatus,
    WorkerType,
)
from simple_orchestrator_core.settings import WebApiSettings

from .db.orchestrator import OrchestratorDB
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


@router.post("/queue", response_model=EnqueueResponse, dependencies=[Depends(_require_api_key)])
async def enqueue(request: Request, req: EnqueueRequest) -> EnqueueResponse:
    db = _state(request).db
    # Validate agent exists (agents live in DB now).
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


@router.patch("/queue/{item_id}", dependencies=[Depends(_require_api_key)])
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
    settings = state.settings
    item = await anyio.to_thread.run_sync(db.dequeue_next)
    if not item:
        return Response(status_code=204)  # type: ignore[return-value]

    agent = await anyio.to_thread.run_sync(lambda: db.get_agent(item.agent_id))
    if not agent:
        # Should never happen if enqueue validates agent existence; fail the item defensively.
        await anyio.to_thread.run_sync(lambda: db.update_queue_item(item.id, status="failed"))
        raise HTTPException(status_code=500, detail="Dequeued item references missing agent")

    session_config = build_session_config(settings=settings, agent=agent, item=item)
    return QueueDequeueResponse(
        item=item,
        vendor=agent.vendor,
        timeout_minutes=agent.task_timeout_minutes,
        session_config=session_config,
    )


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
    await anyio.to_thread.run_sync(lambda: db.save_session(req.record))
    return {"status": "ok"}


@router.patch("/sessions/{session_id}", dependencies=[Depends(_require_api_key)])
async def update_session(request: Request, session_id: str, req: SessionUpdateRequest) -> dict[str, str]:
    db = _state(request).db
    await anyio.to_thread.run_sync(lambda: db.update_session_status(session_id, req))
    return {"status": "ok"}


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
