from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from mewcode.permissions import PermissionMode, PermissionPreflight
from mewcode.providers import ModelRequest
from mewcode.tools import ToolResult, ToolSafety, ValidatedToolCall

from .events import AgentEvent, AgentMode


@dataclass(frozen=True)
class AgentControlContext:
    run_id: str
    iteration: int
    mode: AgentMode
    profile_name: str
    permission_mode: PermissionMode
    max_iterations: int
    allowed_safety: frozenset[ToolSafety]
    parent_request: ModelRequest


@dataclass(frozen=True)
class ForkRequestSeed:
    profile_name: str
    request: ModelRequest
    parent_run_id: str
    parent_iteration: int
    permission_mode: PermissionMode
    max_iterations: int
    allowed_safety: frozenset[ToolSafety]


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    reason: str = ""


class ToolExecutionPolicy(Protocol):
    def evaluate(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> ToolPolicyDecision: ...


class AllowAllToolExecutionPolicy:
    def evaluate(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> ToolPolicyDecision:
        return ToolPolicyDecision(True)


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
    def control_operation(
        self,
        arguments: dict[str, object],
        context: AgentControlContext | None,
    ) -> AgentControlOperation: ...
