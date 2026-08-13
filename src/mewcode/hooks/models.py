from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, TypeAlias

from mewcode.matching import MatchSubjectKind


class HookEvent(StrEnum):
    SESSION_START = "session.start"
    SESSION_END = "session.end"
    TURN_START = "turn.start"
    TURN_END = "turn.end"
    MESSAGE_BEFORE = "message.before"
    MESSAGE_AFTER = "message.after"
    TOOL_BEFORE = "tool.before"
    TOOL_AFTER = "tool.after"
    COMPACT_BEFORE = "system.compact.before"
    COMPACT_AFTER = "system.compact.after"
    SYSTEM_ERROR = "system.error"


class HookSource(StrEnum):
    USER = "user"
    PROJECT = "project"
    PROJECT_LOCAL = "project_local"


class HookMatchKind(StrEnum):
    EXACT = "exact"
    GLOB = "glob"
    REGEX = "regex"


class HookLogic(StrEnum):
    ALL = "all"
    ANY = "any"


class HookOutcomeKind(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    NOT_MATCHED = "not_matched"
    DENIED = "denied"
    CANCELLED = "cancelled"


HookScalar: TypeAlias = str | int | float | bool


@dataclass(frozen=True)
class HookLimits:
    rules_per_file: int = 256
    merged_rules: int = 512
    conditions_per_rule: int = 32
    field_chars: int = 256
    value_chars: int = 4096
    regex_chars: int = 1024
    regex_timeout_seconds: float = 0.05
    prompt_bytes: int = 32 * 1024
    prompt_consume_bytes: int = 64 * 1024
    envelope_bytes: int = 1024 * 1024
    command_output_bytes: int = 64 * 1024
    http_response_bytes: int = 64 * 1024
    deny_reason_chars: int = 2048
    summary_chars: int = 4096
    background_tasks: int = 32
    close_timeout_seconds: float = 5.0
    log_bytes: int = 1024 * 1024
    log_backups: int = 3


DEFAULT_HOOK_LIMITS = HookLimits()


@dataclass(frozen=True)
class HookRuleKey:
    source: HookSource
    path: Path
    index: int


@dataclass(frozen=True)
class HookConditionClause:
    field: str
    match: HookMatchKind
    value: HookScalar
    negate: bool = False
    compiled: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class HookCondition:
    logic: HookLogic
    clauses: tuple[HookConditionClause, ...]


@dataclass(frozen=True)
class HookExecutionControl:
    once: bool = False
    background: bool = False


@dataclass(frozen=True)
class CommandHookAction:
    command: str
    timeout_seconds: int = 60
    control: HookExecutionControl = HookExecutionControl()


@dataclass(frozen=True)
class PromptHookAction:
    content: str
    control: HookExecutionControl = HookExecutionControl()


@dataclass(frozen=True)
class HttpHookAction:
    url: str
    method: str = "POST"
    headers: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    timeout_seconds: int = 30
    control: HookExecutionControl = HookExecutionControl()


@dataclass(frozen=True)
class AgentHookAction:
    task: str
    control: HookExecutionControl = HookExecutionControl()


HookAction: TypeAlias = (
    CommandHookAction | PromptHookAction | HttpHookAction | AgentHookAction
)


@dataclass(frozen=True)
class HookRule:
    key: HookRuleKey
    event: HookEvent
    condition: HookCondition | None
    action: HookAction


@dataclass(frozen=True)
class HookCatalog:
    rules: tuple[HookRule, ...]
    by_event: Mapping[HookEvent, tuple[HookRule, ...]]
    requires_project_trust: bool = False

    @classmethod
    def empty(cls) -> "HookCatalog":
        return cls((), MappingProxyType({}), False)


@dataclass(frozen=True)
class HookEventContext:
    event: HookEvent
    occurred_at: datetime
    values: Mapping[str, object]
    match_kinds: Mapping[str, MatchSubjectKind] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class SerializedHookEnvelope:
    value: Mapping[str, object]
    encoded: bytes
    truncated_fields: tuple[str, ...]


@dataclass(frozen=True)
class HookDecision:
    deny: bool
    reason: str | None = None


@dataclass(frozen=True)
class HookActionOutcome:
    kind: HookOutcomeKind
    decision: HookDecision | None = None
    summary: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class HookDispatchResult:
    decision: HookDecision | None = None


@dataclass(frozen=True)
class HookDiagnostic:
    occurred_at: datetime
    event: HookEvent
    rule: HookRuleKey
    action_type: str
    background: bool
    outcome: HookOutcomeKind
    duration_ms: int
    summary: str


def action_type(action: HookAction) -> str:
    if isinstance(action, CommandHookAction):
        return "command"
    if isinstance(action, PromptHookAction):
        return "prompt"
    if isinstance(action, HttpHookAction):
        return "http"
    return "agent"
