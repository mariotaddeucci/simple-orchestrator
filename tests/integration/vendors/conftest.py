import asyncio
import contextlib
import os
import pathlib
import shutil
from datetime import datetime

import pytest
from simple_orchestrator_core.models.session import SessionRecord

# ---------------------------------------------------------------------------
# Availability probes — run once at collection time
# ---------------------------------------------------------------------------

_COPILOT_SDK_AVAILABLE = False
_CLAUDE_SDK_AVAILABLE = False
_OPENCODE_AVAILABLE = False

with contextlib.suppress(Exception):
    from copilot.client import CopilotClient as _CopilotClient  # noqa: F401

    _COPILOT_SDK_AVAILABLE = True

with contextlib.suppress(Exception):
    from claude_agent_sdk import query as _claude_query  # noqa: F401

    _CLAUDE_SDK_AVAILABLE = True

with contextlib.suppress(Exception):
    from opencode_ai import AsyncOpencode as _AsyncOpencode  # noqa: F401

    _OPENCODE_AVAILABLE = True


def _copilot_authenticated() -> bool:
    if not _COPILOT_SDK_AVAILABLE:
        return False

    async def _probe() -> bool:
        with contextlib.suppress(Exception):
            from copilot.client import CopilotClient

            async with CopilotClient() as client:
                await client.list_models()
            return True
        return False

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_probe())
    finally:
        loop.close()


def _claude_authenticated() -> bool:
    if not _CLAUDE_SDK_AVAILABLE:
        return False
    if not shutil.which("claude"):
        return False
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    claude_dir = pathlib.Path.home() / ".claude"
    if claude_dir.exists():
        for fname in claude_dir.iterdir():
            if "credential" in fname.name.lower() or fname.suffix == ".json":
                return True
    return False


def _opencode_reachable() -> bool:
    if not _OPENCODE_AVAILABLE:
        return False
    try:
        from opencode_ai import AsyncOpencode

        async def _probe() -> bool:
            with contextlib.suppress(Exception):
                async with AsyncOpencode() as client:
                    await client.session.list()
                    return True
            return False

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_probe())
        finally:
            loop.close()
    except Exception:
        return False


@pytest.fixture(scope="session")
def copilot_available():
    return _copilot_authenticated()


@pytest.fixture(scope="session")
def claude_available():
    return _claude_authenticated()


@pytest.fixture(scope="session")
def opencode_reachable():
    return _opencode_reachable()


@pytest.fixture
def session_store():  # noqa: C901
    class _Store:
        def __init__(self) -> None:
            self.records: dict[str, SessionRecord] = {}

        async def save(self, record: SessionRecord) -> None:
            self.records[record.id] = record

        async def update_status(
            self,
            session_id: str,
            status: str,
            *,
            ended_at: datetime | None = None,
            vendor_session_id: str | None = None,
        ) -> None:
            rec = self.records.get(session_id)
            if rec is None:
                return
            rec.status = status
            if ended_at is not None:
                rec.ended_at = ended_at
            if vendor_session_id is not None:
                rec.vendor_session_id = vendor_session_id

        async def get(self, session_id: str) -> SessionRecord | None:
            return self.records.get(session_id)

    return _Store()


@pytest.fixture
def has_ulid_format():
    def _check(s: str) -> bool:
        return len(s) == 26 and s.isalnum()

    return _check


@pytest.fixture
def simple_prompt():
    return "What is 2+2? Respond with the number only, no punctuation."
