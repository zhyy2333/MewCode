from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from mewcode.providers import TokenUsage
from mewcode.permissions import (
    PermissionChallenge,
    PermissionOutcome,
    PermissionSource,
)
from mewcode.tools import ToolCallRequest, ToolExecution


class AgentMode(StrEnum):
    DIRECT = "direct"
    PLAN = "plan"
    EXECUTE = "execute"


class StopReason(StrEnum):
    COMPLETED = "completed"
    OUTPUT_LIMIT = "output_limit"
    EMPTY_RESPONSE = "empty_response"
    ITERATION_LIMIT = "iteration_limit"
    CANCELLED = "cancelled"
    UNKNOWN_TOOL_LIMIT = "unknown_tool_limit"
    STREAM_ERROR = "stream_error"
    ERROR = "error"


@dataclass(frozen=True)
class AgentTextDelta:
    run_id: str
    iteration: int
    text: str


@dataclass(frozen=True)
class AgentToolCall:
    run_id: str
    iteration: int
    request: ToolCallRequest


@dataclass(frozen=True)
class AgentToolResult:
    run_id: str
    iteration: int
    execution: ToolExecution


@dataclass(frozen=True)
class AgentPermissionRequest:
    run_id: str
    iteration: int
    challenge: PermissionChallenge


@dataclass(frozen=True)
class AgentPermissionDecision:
    run_id: str
    iteration: int
    tool_call_id: str
    tool_name: str
    target: str | None
    outcome: PermissionOutcome
    source: PermissionSource
    reason: str


@dataclass(frozen=True)
class AgentTokenUsage:
    run_id: str
    iteration: int
    current: TokenUsage
    cumulative: TokenUsage


ProgressPhase = Literal[
    "run_started",
    "iteration_started",
    "model_completed",
    "tool_batch_started",
    "tool_batch_completed",
]


@dataclass(frozen=True)
class AgentProgress:
    run_id: str
    iteration: int
    phase: ProgressPhase
    completed: int | None = None
    total: int | None = None
    message: str = ""


@dataclass(frozen=True)
class AgentStopped:
    run_id: str
    iteration: int
    reason: StopReason
    final_text: str
    usage: TokenUsage
    error: str | None = None


AgentEvent = (
    AgentTextDelta
    | AgentToolCall
    | AgentToolResult
    | AgentPermissionRequest
    | AgentPermissionDecision
    | AgentTokenUsage
    | AgentProgress
    | AgentStopped
)
