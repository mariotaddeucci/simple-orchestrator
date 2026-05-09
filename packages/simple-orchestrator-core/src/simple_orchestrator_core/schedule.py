from __future__ import annotations

from datetime import UTC, datetime, timedelta

from croniter import croniter


def compute_next_run(
    schedule_type: str,
    *,
    interval_minutes: float | None = None,
    cron_expression: str | None = None,
    base: datetime | None = None,
) -> datetime:
    now = base or datetime.now(UTC)
    if schedule_type == "interval":
        if not interval_minutes or interval_minutes <= 0:
            raise ValueError("interval_minutes required for interval schedule")
        return now + timedelta(minutes=interval_minutes)
    if schedule_type == "cron":
        if not cron_expression:
            raise ValueError("cron_expression required for cron schedule")
        it = croniter(cron_expression, now)
        return it.get_next(datetime).replace(tzinfo=UTC)
    raise ValueError(f"unknown schedule_type: {schedule_type!r}")
