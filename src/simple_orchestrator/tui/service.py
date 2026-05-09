"""Service layer — bridges DB + settings for TUI components."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from croniter import croniter

from simple_orchestrator.cron_runner import _cron_key
from simple_orchestrator.models.agent_record import AgentRecord
from simple_orchestrator.models.queue_item import QueueItem
from simple_orchestrator.polling_runner import _polling_key

if TYPE_CHECKING:
    from simple_orchestrator.db.orchestrator import OrchestratorDB
    from simple_orchestrator.settings import OrchestratorSettings

_FINISHED_LIMIT = 20


class ScheduledEvent:
    def __init__(self, event_type: str, agent_id: str, schedule: str, next_run: datetime) -> None:
        self.event_type = event_type
        self.agent_id = agent_id
        self.schedule = schedule
        self.next_run = next_run


class OrchestratorService:
    def __init__(self, db: OrchestratorDB, settings: OrchestratorSettings) -> None:
        self._db = db
        self._settings = settings

    # ── queue ─────────────────────────────────────────────────────────────────

    def list_pending(self) -> list[QueueItem]:
        return self._db.list_queue(status="pending")

    def list_running(self) -> list[QueueItem]:
        return self._db.list_queue(status="running")

    def list_finished(self) -> list[QueueItem]:
        all_items = self._db.list_queue()
        finished = [i for i in all_items if i.status in ("completed", "failed", "killed", "cancelled") and i.ended_at]
        finished.sort(key=lambda i: i.ended_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return finished[:_FINISHED_LIMIT]

    def enqueue(self, agent_id: str, prompt: str, workdir: str | None = None) -> QueueItem:
        return self._db.enqueue(agent_id=agent_id, prompt=prompt, workdir=workdir)

    def cancel(self, item_id: str) -> None:
        self._db.cancel_queue_item(item_id)

    def kill(self, item: QueueItem) -> None:
        if item.session_id:
            self._db.update_queue_item(item.id, status="killed", ended_at=datetime.now(UTC))

    def queue_stats(self) -> dict[str, int]:
        all_items = self._db.list_queue()
        return {
            "pending": sum(1 for i in all_items if i.status == "pending"),
            "running": sum(1 for i in all_items if i.status == "running"),
            "completed": sum(1 for i in all_items if i.status == "completed"),
            "failed": sum(1 for i in all_items if i.status == "failed"),
        }

    # ── agents ────────────────────────────────────────────────────────────────

    def list_agents(self) -> list[AgentRecord]:
        agents: list[AgentRecord] = []
        for agent_id, agent_s in self._settings.agents.items():
            if not agent_s.vendor:
                continue
            agents.append(
                AgentRecord(
                    id=agent_id,
                    name=agent_s.name,
                    nickname=agent_s.nickname,
                    prompt=agent_s.resolve_prompt(),
                    model=agent_s.model,
                    vendor=agent_s.vendor,
                    workdir=agent_s.workdir,
                    created_at=datetime.now(UTC),
                ),
            )
        return agents

    def agent_labels(self) -> dict[str, str]:
        return {a.id: a.nickname or a.name for a in self.list_agents()}

    # ── scheduled events ──────────────────────────────────────────────────────

    def list_scheduled_events(self) -> list[ScheduledEvent]:
        events: list[ScheduledEvent] = []
        now = datetime.now(UTC)

        for polling in self._settings.pollings:
            key = _polling_key(polling)
            last_run = self._db.get_cron_last_run(key)
            if last_run:
                next_run = datetime.fromtimestamp(last_run.timestamp() + polling.interval_minutes * 60, UTC)
            else:
                next_run = now
            events.append(ScheduledEvent("polling", polling.agent_id, f"every {polling.interval_minutes}m", next_run))

        for cron_cfg in self._settings.crons:
            key = _cron_key(cron_cfg)
            last_run = self._db.get_cron_last_run(key)
            base = last_run.replace(tzinfo=None) if last_run else now.replace(tzinfo=None)
            ci = croniter(cron_cfg.cron, base)
            next_run = ci.get_next(datetime).replace(tzinfo=UTC)
            events.append(ScheduledEvent("cron", cron_cfg.agent_id, cron_cfg.cron, next_run))

        events.sort(key=lambda e: e.next_run)
        return events
