from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from .validators import MAX_PROMPT_LENGTH, ValidAgentId, ValidAlias, ValidDepRef, ValidWorkdir


class TaskSpec(BaseModel):
    """Pydantic schema for batch enqueues (used by MCP / external callers)."""

    alias: Annotated[
        ValidAlias | None,
        Field(
            default=None,
            description="Local name for this task; other tasks in the same batch can depend on it.",
        ),
    ] = None
    agent_id: Annotated[ValidAgentId, Field(description="ID of the agent to handle this task")]
    prompt: Annotated[str, Field(description="Full task description for the agent", max_length=MAX_PROMPT_LENGTH)]
    workdir: Annotated[ValidWorkdir, Field(default=None, description="Optional working directory override")] = None
    depends_on: Annotated[
        list[ValidDepRef],
        Field(
            default_factory=list,
            description="Aliases (from this batch) or existing task IDs this task must wait for",
            max_length=100,
        ),
    ] = Field(default_factory=list)
