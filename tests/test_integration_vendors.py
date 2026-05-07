"""
Integration tests for vendor session flows.

Run with:  uv run pytest tests/test_integration_vendors.py -m integration -v

Prerequisites:
  - copilot: GitHub Copilot CLI must be installed and authenticated
  - claude_code: `claude` CLI must be installed and authenticated
  - opencode: OpenCode server must be running (skipped if unreachable)
"""

import asyncio
import contextlib
from unittest.mock import MagicMock

import pytest

from simple_orchestrator.db.history import SessionHistoryDB
from simple_orchestrator.models.session import SessionConfig
from simple_orchestrator.vendors.claude_code import ClaudeCodeVendor
from simple_orchestrator.vendors.github_copilot import GithubCopilotVendor
from simple_orchestrator.vendors.opencode import OpenCodeVendor

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
    import os
    import pathlib
    import shutil

    if not _CLAUDE_SDK_AVAILABLE:
        return False
    if not shutil.which("claude"):
        return False
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    # Check for OAuth credential files in ~/.claude/
    claude_dir = pathlib.Path.home() / ".claude"
    if claude_dir.exists():
        for fname in claude_dir.iterdir():
            if "credential" in fname.name.lower() or fname.suffix == ".json":
                return True
    return False


_COPILOT_AVAILABLE = _copilot_authenticated()
_CLAUDE_AVAILABLE = _claude_authenticated()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_PROMPT = "What is 2+2? Respond with the number only, no punctuation."


def _has_ulid_format(s: str) -> bool:
    """ULID: 26 alphanumeric chars (Crockford base32)."""
    return len(s) == 26 and s.isalnum()


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


_OPENCODE_REACHABLE = _opencode_reachable()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def history_db(tmp_path):
    db = SessionHistoryDB(tmp_path / "sessions.db")
    await db.connect()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Copilot — gpt-4.1
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _COPILOT_AVAILABLE, reason="copilot not available or not authenticated")
async def test_copilot_gpt41_model_available():
    """gpt-4.1 must appear in the list_models() response."""
    vendor = GithubCopilotVendor(MagicMock(), model="gpt-4.1")
    models = await vendor.list_models()
    model_ids = [m.id for m in models]
    assert "gpt-4.1" in model_ids, f"gpt-4.1 not in {model_ids}"


@pytest.mark.integration
@pytest.mark.skipif(not _COPILOT_AVAILABLE, reason="copilot not available or not authenticated")
async def test_copilot_execute_session_returns_session_id_and_response(history_db):
    """
    execute_session() with gpt-4.1 must yield a session_created event with a
    non-empty session_id, and at least one assistant.message event containing
    the text response.
    """
    from copilot.generated.session_events import AssistantMessageData, SessionEventType

    vendor = GithubCopilotVendor(history_db, model="gpt-4.1")
    config = SessionConfig(prompt=_SIMPLE_PROMPT, model="gpt-4.1")

    stream = await vendor.execute_session(config)
    events = [e async for e in stream]

    # --- session_id ---
    created = next((e for e in events if e.get("type") == "session_created"), None)
    assert created is not None, "No session_created event received"
    vendor_session_id = created["session_id"]
    assert isinstance(vendor_session_id, str), f"session_id must be str, got: {type(vendor_session_id)}"
    assert vendor_session_id, f"session_id must be non-empty, got: {vendor_session_id!r}"

    # --- assistant message text ---
    assistant_events = [
        e
        for e in events
        if e.get("type") == "event"
        and hasattr(e.get("data"), "type")
        and e["data"].type == SessionEventType.ASSISTANT_MESSAGE
    ]
    assert assistant_events, f"No assistant.message events received. All events: {[e.get('type') for e in events]}"

    text_content = "".join(
        ae["data"].data.content for ae in assistant_events if isinstance(ae["data"].data, AssistantMessageData)
    )
    assert text_content.strip(), "Assistant message content is empty"
    assert "4" in text_content, f"Expected '4' in response to '2+2', got: {text_content!r}"


@pytest.mark.integration
@pytest.mark.skipif(not _COPILOT_AVAILABLE, reason="copilot not available or not authenticated")
async def test_copilot_run_and_wait_completes_with_gpt41(history_db):
    """
    Full run() → wait() flow with gpt-4.1 must complete:
      - run() returns a ULID session_id
      - wait() returns a record with status='completed' and vendor='github_copilot'
    """
    vendor = GithubCopilotVendor(history_db, model="gpt-4.1")
    config = SessionConfig(prompt=_SIMPLE_PROMPT, model="gpt-4.1")

    session_id = await vendor.run(config)
    assert _has_ulid_format(session_id), f"run() must return ULID, got: {session_id!r}"

    record = await vendor.wait(session_id)
    assert record is not None, "wait() returned None"
    assert record.status == "completed", f"Expected 'completed', got: {record.status!r}"
    assert record.vendor == "github_copilot"
    assert record.id == session_id
    assert record.vendor_session_id, "vendor_session_id must be populated after run"


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _CLAUDE_AVAILABLE, reason="claude not available or not authenticated")
async def test_claude_code_execute_session_returns_response(history_db):
    """
    execute_session() must yield AssistantMessage events with text content
    that answers '2+2 = 4'.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock

    vendor = ClaudeCodeVendor(history_db)
    config = SessionConfig(prompt=_SIMPLE_PROMPT, max_turns=1)

    stream = await vendor.execute_session(config)
    messages = [m async for m in stream]

    assert messages, "No messages received from execute_session"

    text_parts = [
        block.text
        for msg in messages
        if isinstance(msg, AssistantMessage)
        for block in msg.content
        if isinstance(block, TextBlock)
    ]
    assert text_parts, f"No TextBlock found. Message types: {[type(m).__name__ for m in messages]}"

    full_text = " ".join(text_parts)
    assert "4" in full_text, f"Expected '4' in response to '2+2', got: {full_text!r}"


@pytest.mark.integration
@pytest.mark.skipif(not _CLAUDE_AVAILABLE, reason="claude not available or not authenticated")
async def test_claude_code_run_and_wait_completes(history_db):
    """run() → wait() must return a ULID session_id and a completed record."""
    vendor = ClaudeCodeVendor(history_db)
    config = SessionConfig(prompt=_SIMPLE_PROMPT, max_turns=1)

    session_id = await vendor.run(config)
    assert _has_ulid_format(session_id), f"run() must return ULID, got: {session_id!r}"

    record = await vendor.wait(session_id)
    assert record is not None, "wait() returned None"
    assert record.status == "completed", f"Expected 'completed', got: {record.status!r}"
    assert record.vendor == "claude_code"
    assert record.id == session_id


# ---------------------------------------------------------------------------
# OpenCode — skipped when server is unreachable
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _OPENCODE_REACHABLE, reason="OpenCode server not reachable")
async def test_opencode_execute_session_returns_session_id_and_response(history_db):
    """
    execute_session() must yield session_created event with a non-empty session_id
    and a response event. Text content is verified via session.messages().
    """
    from opencode_ai import AsyncOpencode
    from opencode_ai.types import AssistantMessage as OpenCodeAssistantMessage
    from opencode_ai.types import TextPart
    from opencode_ai.types.session_messages_response import SessionMessagesResponseItem

    vendor = OpenCodeVendor(history_db)
    config = SessionConfig(prompt=_SIMPLE_PROMPT)

    stream = await vendor.execute_session(config)
    events = [e async for e in stream]

    # --- session_id ---
    created = next((e for e in events if e.get("type") == "session_created"), None)
    assert created is not None, "No session_created event received"
    vendor_session_id = created["session_id"]
    assert isinstance(vendor_session_id, str), f"session_id must be str, got: {type(vendor_session_id)}"
    assert vendor_session_id, f"session_id must be non-empty, got: {vendor_session_id!r}"

    # --- response event ---
    response_event = next((e for e in events if e.get("type") == "response"), None)
    assert response_event is not None, "No response event received"
    assistant_msg = response_event["data"]
    assert isinstance(assistant_msg, OpenCodeAssistantMessage), f"Expected AssistantMessage, got {type(assistant_msg)}"
    assert assistant_msg.session_id == vendor_session_id

    # --- fetch text content ---
    async with AsyncOpencode() as client:
        raw_messages: list[SessionMessagesResponseItem] = await client.session.messages(vendor_session_id)

    text_parts = [
        part.text
        for item in raw_messages
        for part in item.parts
        if isinstance(part, TextPart) and item.info.role == "assistant"
    ]
    assert text_parts, "No text parts in assistant messages"
    full_text = " ".join(text_parts)
    assert "4" in full_text, f"Expected '4' in response to '2+2', got: {full_text!r}"


@pytest.mark.integration
@pytest.mark.skipif(not _OPENCODE_REACHABLE, reason="OpenCode server not reachable")
async def test_opencode_run_and_wait_completes(history_db):
    """run() → wait() must return a ULID session_id and a completed record."""
    vendor = OpenCodeVendor(history_db)
    config = SessionConfig(prompt=_SIMPLE_PROMPT)

    session_id = await vendor.run(config)
    assert _has_ulid_format(session_id), f"run() must return ULID, got: {session_id!r}"

    record = await vendor.wait(session_id)
    assert record is not None, "wait() returned None"
    assert record.status == "completed", f"Expected 'completed', got: {record.status!r}"
    assert record.vendor == "opencode"
    assert record.id == session_id
