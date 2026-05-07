from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from simple_orchestrator.models.session import SessionConfig


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
    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]: ...
