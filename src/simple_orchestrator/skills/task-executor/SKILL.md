# Task Executor

Use this skill when you are running as an agent dispatched from the orchestrator queue. It explains how to read your assigned task and how to record a summary note at the end of your session.

## Your task ID

When you are started by the queue runner, your task ID is available in the environment variable `ORCHESTRATOR_TASK_ID`. Read this value at the start of your session — you will need it to fetch task details and to save a note.

## Reading the current task

Use `get_task` with your task ID to retrieve the full prompt and metadata:

```json
{ "task_id": "<value of ORCHESTRATOR_TASK_ID>" }
```

The response includes:
- `prompt` — the full task description you were asked to complete.
- `status` — current status (`running` while you are active).
- `depends_on` — IDs of tasks that had to complete before yours started.
- `note` — any previously saved note for this task (if present).

## Recording a session note

At the **end** of your session, call `add_task_note` to attach a short summary of what was done and whether the objective was achieved:

```json
{
  "task_id": "<value of ORCHESTRATOR_TASK_ID>",
  "note": "Refactored src/payments/charge.py to validate inputs. All tests pass. Objective fully achieved."
}
```

Keep the note concise (a few sentences). Include:
- What was actually done.
- Whether the original objective was fully, partially, or not achieved.
- Any blockers, caveats, or follow-up work needed.

The note is stored alongside the task and can be read by the orchestrating agent or a human reviewer via `get_task` or `list_tasks`.

## Typical workflow

1. Read `ORCHESTRATOR_TASK_ID` from the environment.
2. Call `get_task` to load the full prompt and any context.
3. Carry out the work described in the prompt.
4. Call `add_task_note` with a brief outcome summary before finishing.
