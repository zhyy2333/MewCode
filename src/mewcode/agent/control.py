from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from mewcode.tools import ToolResult

from .events import AgentEvent


class AgentControlOperation(Protocol):
    async def events(self) -> AsyncIterator[AgentEvent]:
        ...

    @property
    def result(self) -> ToolResult:
        ...

    async def cancel(self) -> None:
        ...


@runtime_checkable
class AgentControlTool(Protocol):
    def control_operation(self, arguments: dict[str, object]) -> AgentControlOperation:
        ...
