# Queue Tasks

Use this skill to delegate work to other agents via the orchestrator queue and to monitor task progress.

## Adding tasks to the queue

### Single task

Use `enqueue_task` to add one task to the queue:

```json
{
  "agent_id": "reviewer",
  "prompt": "Review the changes in src/payments/ and report issues.",
  "depends_on": []
}
```

- `agent_id` — ID of the agent that will run the task. Use `list_agents` to discover valid IDs.
- `prompt` — Full description of what the agent should do.
- `depends_on` — (Optional) list of task IDs that must complete successfully before this task starts. If any dependency fails or is cancelled, this task is automatically failed too.

The tool returns a `task_id`. Save it if you need to check the result later.

### Multiple tasks in one call

Use `enqueue_tasks` to submit an entire dependency graph at once. Each task can declare an `alias` that other tasks in the same batch may reference in `depends_on`:

```json
{
  "tasks": [
    {
      "alias": "audit",
      "agent_id": "security",
      "prompt": "Audit src/payments/ for OWASP Top 10 vulnerabilities."
    },
    {
      "alias": "tests",
      "agent_id": "tester",
      "prompt": "Write unit tests for src/payments/ covering the critical paths.",
      "depends_on": ["audit"]
    }
  ]
}
```

You can mix `alias` references and real task IDs (from previous calls) inside `depends_on`.

## Viewing tasks in the queue

### List all tasks

`list_tasks` returns every task with status, prompt preview, agent, timestamps, and linked session ID:

```json
{}
```

### Filter by status

```json
{ "status": "pending" }
```

Valid statuses: `pending`, `running`, `completed`, `failed`, `cancelled`.

### Filter by agent

```json
{ "agent_id": "reviewer" }
```

### Get full details of one task

Use `get_task` with the task ID returned by `enqueue_task` or seen in `list_tasks`:

```json
{ "task_id": "01JXXXXXXXXXXXXXXXXXXXXXXXXX" }
```

The response includes the complete prompt and the `session_id` — use `get_session` to read the full session record.

### Cancel a pending task

```json
{ "task_id": "01JXXXXXXXXXXXXXXXXXXXXXXXXX" }
```

Only tasks with status `pending` can be cancelled; already-running tasks are unaffected.

## Typical delegation workflow

1. Call `list_agents` to discover available agents and their IDs.
2. Call `enqueue_tasks` with the full dependency graph.
3. Poll `list_tasks(status="running")` or `list_tasks(status="pending")` to track progress.
4. When a task reaches `completed`, call `get_task` to get its `session_id`, then `get_session` for the full result.
