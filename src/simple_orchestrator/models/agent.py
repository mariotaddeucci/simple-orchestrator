from typing import Literal

from pydantic import BaseModel


class AgentConfig(BaseModel):
    description: str
    prompt: str
    model: str | None = None
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    skills: list[str] | None = None
    mcp_servers: list[str] | None = None
    initial_prompt: str | None = None
    max_turns: int | None = None
    background: bool | None = None
    effort: Literal["low", "medium", "high", "max"] | int | None = None
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"] | None = None
