from unittest.mock import MagicMock

import pytest
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_worker.vendors.github_copilot import GithubCopilotVendor


@pytest.mark.integration
@pytest.mark.vendor_cost
async def test_copilot_gpt41_model_available(copilot_available):
    """gpt-4.1 must appear in the list_models() response."""
    if not copilot_available:
        pytest.skip("copilot not available or not authenticated")

    vendor = GithubCopilotVendor(MagicMock(), model="gpt-4.1")
    try:
        models = await vendor.list_models()
    except Exception as e:
        if "rate limit" in str(e).lower():
            pytest.skip(f"Skipping due to rate limit: {e}")
        raise
    model_ids = [m.id for m in models]
    assert "gpt-4.1" in model_ids, f"gpt-4.1 not in {model_ids}"


@pytest.mark.integration
@pytest.mark.vendor_cost
async def test_copilot_execute_session_returns_session_id_and_response(copilot_available, session_store, simple_prompt):
    """
    execute_session() with gpt-4.1 must yield a session_created event with a
    non-empty session_id, and at least one assistant.message event containing
    the text response.
    """
    if not copilot_available:
        pytest.skip("copilot not available or not authenticated")

    from copilot.generated.session_events import AssistantMessageData, SessionEventType

    vendor = GithubCopilotVendor(session_store, model="gpt-4.1")
    config = SessionConfig(prompt=simple_prompt, model="gpt-4.1")

    stream = await vendor.execute_session(config)
    try:
        events = [e async for e in stream]
    except Exception as e:
        if "rate limit" in str(e).lower():
            pytest.skip(f"Skipping due to rate limit: {e}")
        raise

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
@pytest.mark.vendor_cost
async def test_copilot_run_and_wait_completes_with_gpt41(
    copilot_available,
    session_store,
    simple_prompt,
    has_ulid_format,
):
    """
    Full run() flow with gpt-4.1 must complete:
      - run() returns a tuple (session_id, status) where session_id is a ULID
      - session record in store has status='completed' and vendor='github_copilot'
    """
    if not copilot_available:
        pytest.skip("copilot not available or not authenticated")

    vendor = GithubCopilotVendor(session_store, model="gpt-4.1")
    config = SessionConfig(prompt=simple_prompt, model="gpt-4.1")

    try:
        session_id, _status = await vendor.run(config)
    except Exception as e:
        if "rate limit" in str(e).lower():
            pytest.skip(f"Skipping due to rate limit: {e}")
        raise

    assert has_ulid_format(session_id), f"run() must return ULID in tuple, got: {session_id!r}"

    record = await session_store.get(session_id)
    assert record is not None, "session record not found in store"
    assert record.status == "completed", f"Expected 'completed', got: {record.status!r}"
    assert record.vendor == "github_copilot"
    assert record.id == session_id
    assert record.vendor_session_id, "vendor_session_id must be populated after run"
