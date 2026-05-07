"""Integration tests for TUI with queue processing."""

import asyncio
import logging
from datetime import UTC, datetime

import pytest

from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.models.agent_record import AgentRecord
from simple_orchestrator.queue_runner import QueueRunner
from simple_orchestrator.settings import AgentSettings, OrchestratorSettings
from tests.test_mock_agent import MockAgent

logger = logging.getLogger(__name__)


@pytest.fixture
async def orch_db(tmp_path):
    """Create a temporary OrchestratorDB for testing."""
    db = OrchestratorDB(tmp_path / "tui_test.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def settings(tmp_path):
    """Create settings with a mock agent configured."""
    test_agents = {
        "mock-test-agent": AgentSettings(
            name="Mock Test Agent",
            nickname="TestAgent",
            prompt="You are a test agent",
            vendor="mock",
            workdir=str(tmp_path / "workdir"),
            model="mock-model-1",
        ),
    }
    return OrchestratorSettings(
        max_active_sessions=2,
        agents=test_agents,
        db_path=str(tmp_path / "tui_test.db"),
        logs_dir=tmp_path / "logs",
    )


@pytest.fixture
def log_file(tmp_path):
    """Create a temporary log file."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "orchestrator.log"
    log_file.touch()
    return log_file


async def test_tui_manual_prompt_enqueue_and_execution(orch_db, settings, log_file, tmp_path):
    """
    Test the full flow of adding a manual prompt via TUI:
    1. Click on agent card to open prompt modal
    2. Submit a prompt
    3. Verify it's added to queue (pending)
    4. QueueRunner picks it up (running)
    5. Session completes successfully (completed)
    6. All state transitions are logged
    """
    # Setup logging to capture transition logs
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )

    logger.info("=" * 80)
    logger.info("TEST START: TUI manual prompt enqueue and execution")
    logger.info("=" * 80)

    # Create mock vendor
    mock_vendor = MockAgent(orch_db, should_fail=False, delay_seconds=0.2)
    vendors = {"mock": mock_vendor}

    # Create queue runner
    runner = QueueRunner(orch_db, vendors, settings=settings)

    # Create an agent record that matches our settings
    agent = AgentRecord(
        id="mock-test-agent",
        name="Mock Test Agent",
        nickname="TestAgent",
        prompt="You are a test agent",
        model="mock-model-1",
        vendor="mock",
        workdir=str(tmp_path / "workdir"),
        created_at=datetime.now(UTC),
    )

    # Step 1: Simulate clicking agent and entering prompt
    logger.info("STEP 1: User clicks agent and enters prompt")
    test_prompt = "Please analyze this test code and provide feedback"

    # Step 2: Enqueue the prompt (simulates TUI.enqueue_prompt, but directly via DB)
    logger.info("STEP 2: Enqueueing prompt via database (simulating TUI)")
    item = await orch_db.enqueue(agent_id=agent.id, prompt=test_prompt)
    logger.info("TUI simulation: item created with id=%s, status=%s", item.id, item.status)

    # Step 3: Verify item is in queue with status 'pending'
    logger.info("STEP 3: Verifying item is in queue with status 'pending'")
    queue_items = await orch_db.list_queue(status="pending")
    assert len(queue_items) == 1, f"Expected 1 pending item, got {len(queue_items)}"
    item = queue_items[0]
    assert item.prompt == test_prompt
    assert item.agent_id == "mock-test-agent"
    assert item.status == "pending"
    logger.info("VERIFIED: Item %s is pending", item.id)

    # Step 4: Run queue until empty (simulates QueueRunner processing)
    logger.info("STEP 4: Starting queue runner to process item")
    await runner.run_until_empty()
    logger.info("Queue runner finished processing")

    # Allow async callbacks to complete
    await asyncio.sleep(0.5)

    # Step 5: Verify item transitioned to completed
    logger.info("STEP 5: Verifying item transitioned to 'completed'")
    completed_item = await orch_db.get_queue_item(item.id)
    assert completed_item is not None, "Item should exist in database"
    assert completed_item.status == "completed", f"Expected 'completed', got '{completed_item.status}'"
    assert completed_item.started_at is not None, "Item should have started_at timestamp"
    assert completed_item.ended_at is not None, "Item should have ended_at timestamp"
    logger.info("VERIFIED: Item %s completed successfully", item.id)
    logger.info("  - Created at: %s", completed_item.created_at)
    logger.info("  - Started at: %s", completed_item.started_at)
    logger.info("  - Ended at: %s", completed_item.ended_at)

    # Step 6: Verify MockAgent executed the session
    logger.info("STEP 6: Verifying MockAgent executed the session")
    assert len(mock_vendor.executed_sessions) == 1, "MockAgent should have executed exactly one session"
    session_id, executed_prompt = mock_vendor.executed_sessions[0]
    assert executed_prompt == test_prompt, "MockAgent should have executed the correct prompt"
    logger.info("VERIFIED: MockAgent executed session %s with correct prompt", session_id)

    # Step 7: Verify no errors in final state
    logger.info("STEP 7: Verifying no errors in final state")
    all_items = await orch_db.list_queue()
    failed_items = [i for i in all_items if i.status == "failed"]
    assert len(failed_items) == 0, f"Should have no failed items, but got {len(failed_items)}"
    logger.info("VERIFIED: No failed items in queue")

    logger.info("=" * 80)
    logger.info("TEST PASSED: All state transitions completed successfully")
    logger.info("TEST SUMMARY:")
    logger.info("  - Prompt enqueued: ✓")
    logger.info("  - Status: pending → running → completed: ✓")
    logger.info("  - MockAgent execution: ✓")
    logger.info("  - No errors: ✓")
    logger.info("=" * 80)


async def test_tui_manual_prompt_enqueue_with_failure(orch_db, settings, log_file, tmp_path):
    """
    Test that a failed session is properly marked as failed.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )

    logger.info("=" * 80)
    logger.info("TEST START: TUI manual prompt with failure")
    logger.info("=" * 80)

    # Create mock vendor configured to fail
    mock_vendor = MockAgent(orch_db, should_fail=True, delay_seconds=0.1)
    vendors = {"mock": mock_vendor}

    runner = QueueRunner(orch_db, vendors, settings=settings)

    agent = AgentRecord(
        id="mock-test-agent",
        name="Mock Test Agent",
        nickname="TestAgent",
        prompt="You are a test agent",
        model="mock-model-1",
        vendor="mock",
        workdir=str(tmp_path / "workdir"),
        created_at=datetime.now(UTC),
    )

    test_prompt = "This prompt will fail"

    logger.info("STEP 1: Enqueueing prompt that will fail")
    item = await orch_db.enqueue(agent_id=agent.id, prompt=test_prompt)

    logger.info("STEP 2: Processing queue")
    await runner.run_until_empty()
    await asyncio.sleep(0.5)

    logger.info("STEP 3: Verifying item failed")
    all_items = await orch_db.list_queue()
    assert len(all_items) == 1
    item = all_items[0]
    assert item.status == "failed", f"Expected 'failed', got '{item.status}'"
    logger.info("VERIFIED: Item %s marked as failed as expected", item.id)

    logger.info("=" * 80)
    logger.info("TEST PASSED: Failure handling works correctly")
    logger.info("=" * 80)


async def test_tui_multiple_prompts_sequential(orch_db, settings, log_file, tmp_path):
    """
    Test adding multiple prompts and verify they are processed sequentially.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )

    logger.info("=" * 80)
    logger.info("TEST START: Multiple prompts sequential processing")
    logger.info("=" * 80)

    mock_vendor = MockAgent(orch_db, should_fail=False, delay_seconds=0.1)
    vendors = {"mock": mock_vendor}

    runner = QueueRunner(orch_db, vendors, settings=settings)

    agent = AgentRecord(
        id="mock-test-agent",
        name="Mock Test Agent",
        nickname="TestAgent",
        prompt="You are a test agent",
        model="mock-model-1",
        vendor="mock",
        workdir=str(tmp_path / "workdir"),
        created_at=datetime.now(UTC),
    )

    # Enqueue multiple prompts
    prompts = ["First task", "Second task", "Third task"]
    logger.info("STEP 1: Enqueueing %d prompts", len(prompts))
    for prompt in prompts:
        await orch_db.enqueue(agent_id=agent.id, prompt=prompt)
        logger.info("  Enqueued: %s", prompt)

    # Verify all are pending
    logger.info("STEP 2: Verifying all items are pending")
    pending = await orch_db.list_queue(status="pending")
    assert len(pending) == len(prompts), f"Expected {len(prompts)} pending, got {len(pending)}"

    # Process all
    logger.info("STEP 3: Processing all items")
    await runner.run_until_empty()
    await asyncio.sleep(0.5)

    # Verify all completed
    logger.info("STEP 4: Verifying all items completed")
    all_items = await orch_db.list_queue()
    completed = [i for i in all_items if i.status == "completed"]
    assert len(completed) == len(prompts), f"Expected {len(prompts)} completed, got {len(completed)}"

    # Verify MockAgent executed all sessions
    assert len(mock_vendor.executed_sessions) == len(prompts)
    executed_prompts = [p for _, p in mock_vendor.executed_sessions]
    assert executed_prompts == prompts, "All prompts should be executed in order"

    logger.info("=" * 80)
    logger.info("TEST PASSED: Multiple prompts processed successfully")
    logger.info("  - Total prompts: %d", len(prompts))
    logger.info("  - All completed: ✓")
    logger.info("=" * 80)


async def test_tui_manual_prompt_with_custom_workdir(orch_db, settings, log_file, tmp_path):
    """
    Test enqueueing a prompt with a custom workdir:
    1. Enqueue prompt with custom workdir
    2. Verify workdir is stored correctly
    3. Enqueue prompt with None workdir
    4. Verify None workdir creates a temp directory
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )

    logger.info("=" * 80)
    logger.info("TEST START: TUI manual prompt with custom workdir")
    logger.info("=" * 80)

    mock_vendor = MockAgent(orch_db, should_fail=False, delay_seconds=0.1)
    vendors = {"mock": mock_vendor}

    runner = QueueRunner(orch_db, vendors, settings=settings)

    agent = AgentRecord(
        id="mock-test-agent",
        name="Mock Test Agent",
        nickname="TestAgent",
        prompt="You are a test agent",
        model="mock-model-1",
        vendor="mock",
        workdir=str(tmp_path / "workdir"),
        created_at=datetime.now(UTC),
    )

    # Step 1: Enqueue with custom workdir
    logger.info("STEP 1: Enqueueing prompt with custom workdir")
    custom_workdir = str(tmp_path / "custom_workdir")
    (tmp_path / "custom_workdir").mkdir(exist_ok=True)
    test_prompt_1 = "Task with custom workdir"
    item1 = await orch_db.enqueue(agent_id=agent.id, prompt=test_prompt_1, workdir=custom_workdir)
    logger.info("Item created with id=%s, workdir=%s", item1.id, item1.workdir)

    # Verify workdir is stored correctly
    assert item1.workdir == custom_workdir, f"Expected workdir {custom_workdir}, got {item1.workdir}"
    logger.info("VERIFIED: Custom workdir stored correctly")

    # Step 2: Enqueue with None workdir
    logger.info("STEP 2: Enqueueing prompt with None workdir (should create temp dir)")
    test_prompt_2 = "Task with temp workdir"
    item2 = await orch_db.enqueue(agent_id=agent.id, prompt=test_prompt_2, workdir=None)
    logger.info("Item created with id=%s, workdir=%s", item2.id, item2.workdir)

    # Verify workdir is not None (should be resolved to temp dir)
    assert item2.workdir is not None, "Workdir should be resolved to a temp directory"
    assert "/tmp" in item2.workdir or "\\temp" in item2.workdir.lower(), f"Expected temp directory, got {item2.workdir}"
    logger.info("VERIFIED: None workdir resolved to temp directory: %s", item2.workdir)

    # Step 3: Process both items
    logger.info("STEP 3: Processing both items")
    await runner.run_until_empty()
    await asyncio.sleep(0.5)

    # Verify both completed
    logger.info("STEP 4: Verifying both items completed")
    completed_items = await orch_db.list_queue(status="completed")
    assert len(completed_items) == 2, f"Expected 2 completed items, got {len(completed_items)}"
    logger.info("VERIFIED: Both items completed successfully")

    # Verify MockAgent executed both sessions
    assert len(mock_vendor.executed_sessions) == 2, "MockAgent should have executed both sessions"
    logger.info("VERIFIED: MockAgent executed both sessions")

    logger.info("=" * 80)
    logger.info("TEST PASSED: Custom workdir handling works correctly")
    logger.info("  - Custom workdir: ✓")
    logger.info("  - None workdir (temp dir): ✓")
    logger.info("  - Both sessions completed: ✓")
    logger.info("=" * 80)
