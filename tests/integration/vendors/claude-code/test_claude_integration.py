import pytest
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_worker.vendors.claude_code import ClaudeCodeVendor


@pytest.mark.integration
@pytest.mark.vendor_cost
async def test_claude_code_execute_session_returns_response(claude_available, session_store, simple_prompt):
    """
    execute_session() must yield AssistantMessage events with text content
    that answers '2+2 = 4'.
    """
    if not claude_available:
        pytest.skip("claude not available or not authenticated")

    from claude_agent_sdk import AssistantMessage, TextBlock

    vendor = ClaudeCodeVendor(session_store)
    config = SessionConfig(prompt=simple_prompt, max_turns=1)

    stream = await vendor.execute_session(config)
    try:
        messages = [m async for m in stream]
    except Exception as e:
        if "rate limit" in str(e).lower():
            pytest.skip(f"Skipping due to rate limit: {e}")
        raise

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
@pytest.mark.vendor_cost
async def test_claude_code_run_and_wait_completes(claude_available, session_store, simple_prompt, has_ulid_format):
    """run() must return a ULID session_id and result in a completed record."""
    if not claude_available:
        pytest.skip("claude not available or not authenticated")

    vendor = ClaudeCodeVendor(session_store)
    config = SessionConfig(prompt=simple_prompt, max_turns=1)

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
    assert record.vendor == "claude_code"
    assert record.id == session_id
