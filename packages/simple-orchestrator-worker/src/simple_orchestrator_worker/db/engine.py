from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

# Imported here to register tables with SQLModel.metadata before create_all.
# These imports must happen after SQLModel is configured.
import simple_orchestrator_worker.models.memory_record
import simple_orchestrator_worker.models.queue_item
import simple_orchestrator_worker.models.session  # noqa: F401


def build_engine(db_path: str | Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine
