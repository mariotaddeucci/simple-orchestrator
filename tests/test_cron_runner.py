"""Integration tests for CronRunner."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from simple_orchestrator.cron_runner import CronRunner, _cron_key
from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.settings import CronSettings, OrchestratorSettings


@pytest.fixture
async def db(tmp_path):
    db = OrchestratorDB(tmp_path / "cron.db")
    await db.connect()
    yield db
    await db.close()


def _make_settings(*crons: CronSettings) -> OrchestratorSettings:
    return OrchestratorSettings(crons=list(crons))


async def test_first_run_enqueues_immediately(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="do stuff", cron="0 * * * *")
    settings = _make_settings(cron_cfg)

    runner = CronRunner(db, settings=settings)
    await runner._tick()

    items = await db.list_queue(status="pending")
    assert len(items) == 1
    assert items[0].prompt == "do stuff"


async def test_skips_when_not_due(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="periodic task", cron="0 * * * *")
    settings = _make_settings(cron_cfg)
    runner = CronRunner(db, settings=settings)

    # Mark as just run so next run is ~1 hour away
    key = _cron_key(cron_cfg)
    await db.set_cron_last_run(key, datetime.now(UTC))

    await runner._tick()

    items = await db.list_queue(status="pending")
    assert len(items) == 0


async def test_enqueues_when_overdue(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="overdue task", cron="0 * * * *")
    settings = _make_settings(cron_cfg)
    runner = CronRunner(db, settings=settings)

    # Set last_run to 2 hours ago so it's overdue
    key = _cron_key(cron_cfg)
    await db.set_cron_last_run(key, datetime.now(UTC) - timedelta(hours=2))

    await runner._tick()

    items = await db.list_queue(status="pending")
    assert len(items) == 1


async def test_skips_duplicate_pending(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="dup task", cron="0 * * * *")
    settings = _make_settings(cron_cfg)
    runner = CronRunner(db, settings=settings)

    # First tick enqueues
    await runner._tick()
    # Second tick should skip because item is still pending
    await runner._tick()

    items = await db.list_queue(status="pending")
    assert len(items) == 1  # only one item, not two


async def test_cron_key_is_deterministic():
    cfg = CronSettings(agent_id="a1", prompt="hello", cron="*/5 * * * *")
    k1 = _cron_key(cfg)
    k2 = _cron_key(cfg)
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex digest


async def test_start_stop_lifecycle(db):
    settings = _make_settings()  # no crons, so no enqueue activity
    runner = CronRunner(db, settings=settings, check_interval=0.05)

    await runner.start()
    assert runner._running is True
    await asyncio.sleep(0.1)
    await runner.stop()
    assert runner._running is False


async def test_no_crons_does_nothing(db):
    settings = OrchestratorSettings()
    runner = CronRunner(db, settings=settings)
    await runner._tick()  # should not raise or enqueue anything

    items = await db.list_queue()
    assert len(items) == 0
