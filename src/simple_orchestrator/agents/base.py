from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from ..models.agent import AgentConfig
from ..models.session import SessionConfig


class BaseAgentService(ABC):
    """Shared interface for agents and subagents across all vendors."""

    @abstractmethod
    async def trigger(
        self,
        *,
        model: str,
        prompt: str,
        workdir: str,
    ) -> None: ...

    @abstractmethod
    async def execute_session(
        self, config: SessionConfig
    ) -> AsyncIterator[Any]: ...
