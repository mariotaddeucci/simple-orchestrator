from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

_STATUS_STYLE: dict[str, str] = {
    "pending": "#f1fa8c",
    "running": "#8be9fd",
    "completed": "#50fa7b",
    "failed": "#ff5555",
    "killed": "#ff5555",
    "cancelled": "#6272a4",
}

_LOG_LEVEL_STYLE: dict[str, str] = {
    "DEBUG": "#6272a4",
    "INFO": "#f8f8f2",
    "WARNING": "#ffb86c",
    "ERROR": "bold #ff5555",
    "CRITICAL": "bold #ff5555 on #44475a",
}


def tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    chunk_size = 8192
    lines: list[str] = []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        remaining = fh.tell()
        buf = b""
        while remaining > 0 and len(lines) <= n:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            fh.seek(remaining)
            buf = fh.read(read_size) + buf
            lines = buf.decode("utf-8", errors="replace").splitlines(keepends=True)
    return lines[-n:]


def parse_log_line(line: str) -> tuple[str, str, str, str]:
    parts = line.rstrip("\n").split(None, 3)
    if len(parts) == 4:
        return parts[0], parts[1].strip(), parts[2].strip(), parts[3]
    return "", "INFO", "", line.rstrip("\n")


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def elapsed(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "—"
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    finish = end or datetime.now(UTC)
    if finish.tzinfo is None:
        finish = finish.replace(tzinfo=UTC)
    total = int((finish - start).total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def truncate(text: str, max_len: int = 60) -> str:
    text = text.replace("\n", " ").strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def styled(text: str, status: str) -> str:
    style = _STATUS_STYLE.get(status, "")
    return f"[{style}]{text}[/]" if style else text


def format_next_run(next_run: datetime) -> str:
    now = datetime.now(UTC)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=UTC)
    total_seconds = int((next_run - now).total_seconds())
    if total_seconds < 0:
        return "overdue"
    if total_seconds < 60:
        return f"in {total_seconds}s"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"in {minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"in {hours}h"
    return f"in {hours // 24}d"
