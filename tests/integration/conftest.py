from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport
from simple_orchestrator_api_client.client import OrchestratorApiClient
from simple_orchestrator_database import OrchestratorDB
from simple_orchestrator_webapi.api import create_app
from utils import InProcessOrchestratorClient


@pytest.fixture
def orch_db_path(tmp_path):
    return tmp_path / "integration_test.db"


@pytest.fixture
def orch_db(orch_db_path):
    db = OrchestratorDB(orch_db_path)
    db.connect()
    yield db
    db.close()


@pytest.fixture
async def app(orch_db_path) -> AsyncGenerator[FastAPI]:
    # Set the environment variables so the app uses our test database
    os.environ["ORCHESTRATOR_DB_PATH"] = str(orch_db_path)
    os.environ["ORCHESTRATOR_API_KEY"] = "test-api-key"

    # Import inside to ensure env vars are picked up if they affect module-level state
    app = create_app()
    async with LifespanManager(app):
        yield app


@pytest.fixture
async def distributed_client(app: FastAPI) -> AsyncGenerator[OrchestratorApiClient]:
    transport = ASGITransport(app=app)
    return OrchestratorApiClient(
        base_url="http://testserver",
        api_key="test-api-key",
        transport=transport,
    )


@pytest.fixture
def standalone_client(orch_db):
    return InProcessOrchestratorClient(orch_db)


@pytest.fixture(params=["standalone", "distributed"])
async def orchestrator_client(request, standalone_client, distributed_client):
    if request.param == "standalone":
        yield standalone_client
    else:
        yield distributed_client
