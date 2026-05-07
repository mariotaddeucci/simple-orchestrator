"""Integration tests for CronRunner."""

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from simple_orchestrator.cron_runner import CronRunner, _cron_key
from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.settings import CronSettings, OrchestratorSettings


@pytest.fixture
def db(tmp_path):
    db = OrchestratorDB(tmp_path / "cron.db")
    db.connect()
    yield db
    db.close()


def _make_settings(*crons: CronSettings) -> OrchestratorSettings:
    return OrchestratorSettings(crons=list(crons))


def test_first_run_enqueues_immediately(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="do stuff", cron="0 * * * *")
    settings = _make_settings(cron_cfg)

    runner = CronRunner(db, settings=settings)
    runner._tick()

    items = db.list_queue(status="pending")
    assert len(items) == 1
    assert items[0].prompt == "do stuff"


def test_skips_when_not_due(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="periodic task", cron="0 * * * *")
    settings = _make_settings(cron_cfg)
    runner = CronRunner(db, settings=settings)

    # Mark as just run so next run is ~1 hour away
    key = _cron_key(cron_cfg)
    db.set_cron_last_run(key, datetime.now(UTC))

    runner._tick()

    items = db.list_queue(status="pending")
    assert len(items) == 0


def test_enqueues_when_overdue(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="overdue task", cron="0 * * * *")
    settings = _make_settings(cron_cfg)
    runner = CronRunner(db, settings=settings)

    # Set last_run to 2 hours ago so it's overdue
    key = _cron_key(cron_cfg)
    db.set_cron_last_run(key, datetime.now(UTC) - timedelta(hours=2))

    runner._tick()

    items = db.list_queue(status="pending")
    assert len(items) == 1


def test_skips_duplicate_pending(db):
    agent_id = "test-agent-A"
    cron_cfg = CronSettings(agent_id=agent_id, prompt="dup task", cron="0 * * * *")
    settings = _make_settings(cron_cfg)
    runner = CronRunner(db, settings=settings)

    # First tick enqueues
    runner._tick()
    # Second tick should skip because item is still pending
    runner._tick()

    items = db.list_queue(status="pending")
    assert len(items) == 1  # only one item, not two


def test_cron_key_is_deterministic():
    cfg = CronSettings(agent_id="a1", prompt="hello", cron="*/5 * * * *")
    k1 = _cron_key(cfg)
    k2 = _cron_key(cfg)
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex digest


def test_start_stop_lifecycle(db):
    settings = _make_settings()  # no crons, so no enqueue activity
    runner = CronRunner(db, settings=settings, check_interval=0.05)

    t = threading.Thread(target=runner.start, daemon=True)
    t.start()
    assert runner._running is True
    time.sleep(0.1)
    runner.stop()
    t.join(timeout=1.0)
    assert runner._running is False


def test_no_crons_does_nothing(db):
    settings = OrchestratorSettings()
    runner = CronRunner(db, settings=settings)
    runner._tick()  # should not raise or enqueue anything

    items = db.list_queue()
    assert len(items) == 0
