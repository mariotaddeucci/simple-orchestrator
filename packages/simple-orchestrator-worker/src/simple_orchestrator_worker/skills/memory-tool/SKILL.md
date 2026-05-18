# Memory Tool

Use this skill to persist context, state, or notes between agent executions via the orchestrator's memory tools.

**Note**: This skill currently only works in **standalone mode**. It is non-functional in distributed mode because the necessary memory management methods are missing from the REST API and the async client.

## Why use memory?

Each agent session starts fresh. Memories let an agent remember what it learned or produced in earlier runs — useful for incremental work, resumable pipelines, and sharing context between agents.

## Saving a memory

Use `save_memory` to create a new memory entry:

```json
{
  "agent_id": "reviewer",
  "description": "Last reviewed commit range",
  "content": "Reviewed commits from abc123 to def456. Found 2 style issues in src/api.py. No security issues."
}
```

- `agent_id` — ID of the agent that owns this memory.
- `description` — One-line summary shown in `list_memories` (max 200 characters). Keep it concise and searchable.
- `content` — Full memory content (context, state, notes, JSON, etc.). Max 100 000 characters.

The tool returns a `memory_id`. Save it if you want to retrieve or delete the entry by ID later.

Each call to `save_memory` creates a **new** entry — it does not update an existing one. To replace a memory, save a new one and delete the old one.

## Listing memories

Use `list_memories` to see what has been saved. This returns `memory_id`, `agent_id`, `description`, and `updated_at` — **no full content**.

### All memories (all agents)

```json
{}
```

### Memories for a specific agent

```json
{ "agent_id": "reviewer" }
```

Read the `description` field to decide which entry to retrieve.

## Retrieving a memory

Use `get_memory` to load the full content of one entry:

```json
{ "memory_id": "01JXXXXXXXXXXXXXXXXXXXXXXXXX" }
```

The response includes `content`, `description`, `agent_id`, and `updated_at`.

## Deleting a memory

Use `delete_memory` to remove an entry when it is no longer needed:

```json
{ "memory_id": "01JXXXXXXXXXXXXXXXXXXXXXXXXX" }
```

This is a no-op if the ID does not exist.

## Typical memory workflow

### Writing context at the end of a session

Before finishing, call `save_memory` to record what was done and what should happen next:

```json
{
  "agent_id": "reviewer",
  "description": "Review checkpoint — 2025-05-03",
  "content": "Reviewed src/payments/. Issues: missing input validation in charge.py:42. Next: check src/auth/."
}
```

### Reading context at the start of a new session

At the beginning of a new run, call `list_memories` for your agent ID, then `get_memory` on the most relevant entry to restore context:

1. `list_memories({ "agent_id": "reviewer" })` — scan descriptions.
2. `get_memory({ "memory_id": "..." })` — load the full content.
3. Continue from where you left off.

### Replacing a stale memory

1. `save_memory(...)` — write the updated entry, note the new `memory_id`.
2. `delete_memory({ "memory_id": "<old_id>" })` — remove the outdated entry.
