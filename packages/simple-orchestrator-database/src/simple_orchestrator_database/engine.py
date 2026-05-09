from __future__ import annotations

from pathlib import Path

import simple_orchestrator_core.models.agent_record
import simple_orchestrator_core.models.event_record
import simple_orchestrator_core.models.mcp_record
import simple_orchestrator_core.models.memory_record
import simple_orchestrator_core.models.queue_item
import simple_orchestrator_core.models.session
import simple_orchestrator_core.models.worker_heartbeat_record  # noqa: F401
from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine


def build_engine(db_path: str | Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine
