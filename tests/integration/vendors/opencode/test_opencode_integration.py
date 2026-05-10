import pytest
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_worker.vendors.opencode import OpenCodeVendor


@pytest.mark.integration
@pytest.mark.vendor_cost
async def test_opencode_execute_session_returns_session_id_and_response(
    opencode_reachable,
    session_store,
    simple_prompt,
):
    """
    execute_session() must yield session_created event with a non-empty session_id
    and a response event. Text content is verified via session.messages().
    """
    if not opencode_reachable:
        pytest.skip("OpenCode server not reachable")

    from opencode_ai import AsyncOpencode
    from opencode_ai.types import AssistantMessage as OpenCodeAssistantMessage
    from opencode_ai.types import TextPart
    from opencode_ai.types.session_messages_response import SessionMessagesResponseItem

    vendor = OpenCodeVendor(session_store)
    config = SessionConfig(prompt=simple_prompt)

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
@pytest.mark.vendor_cost
async def test_opencode_run_and_wait_completes(opencode_reachable, session_store, simple_prompt, has_ulid_format):
    """run() must return a ULID session_id and result in a completed record."""
    if not opencode_reachable:
        pytest.skip("OpenCode server not reachable")

    vendor = OpenCodeVendor(session_store)
    config = SessionConfig(prompt=simple_prompt)

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
    assert record.vendor == "opencode"
    assert record.id == session_id
