from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from mewcode.permissions import PermissionMode
from mewcode.providers import TokenUsage


AGENT_NAME_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
MAX_DEFINITION_FILE_BYTES = 64 * 1024
MAX_CANDIDATES_PER_ROOT = 256
MAX_SELECTED_PROMPT_BYTES = 1024 * 1024
MAX_TASK_BYTES = 64 * 1024
MAX_RESULT_CHARS = 20_000
MAX_ACTIVE_TASKS = 8
MAX_NOTIFICATION_BATCH = 16
MAX_NOTIFICATION_BYTES = 64 * 1024
MAX_RETAINED_TASKS = 128
TASK_CLOSE_TIMEOUT_SECONDS = 5.0
FOREGROUND_TIMEOUT_SECONDS = 10.0
SUBAGENT_EXECUTION_TIMEOUT_SECONDS = 300.0
MAX_DEFINITION_TURNS = 100
MAX_DIAGNOSTIC_CHARS = 512


class AgentDefinitionLayer(IntEnum):
    PLUGIN = 0
    BUILTIN = 1
    USER = 2
    PROJECT = 3


class AgentIsolation(StrEnum):
    SHARED = "shared"
    WORKTREE = "worktree"


@dataclass(frozen=True)
class AgentDefinitionSource:
    layer: AgentDefinitionLayer
    root: Path
    path: Path
    entry_name: str
    origin: str
    error: str | None = None


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    tools: tuple[str, ...]
    disallowed_tools: tuple[str, ...]
    model: str
    max_turns: int
    permission_mode: PermissionMode
    system_prompt: str
    source: AgentDefinitionSource
    isolation: AgentIsolation = AgentIsolation.SHARED


@dataclass(frozen=True)
class AgentDefinitionDiagnostic:
    name: str
    source: AgentDefinitionSource
    message: str

    def __post_init__(self) -> None:
        if len(self.message) > MAX_DIAGNOSTIC_CHARS:
            object.__setattr__(
                self,
                "message",
                self.message[:MAX_DIAGNOSTIC_CHARS] + "…",
            )


@dataclass(frozen=True)
class AgentDefinitionCatalog:
    definitions: Mapping[str, AgentDefinition]
    diagnostics: tuple[AgentDefinitionDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        ordered = {
            name: self.definitions[name]
            for name in sorted(self.definitions, key=lambda value: (value.casefold(), value))
        }
        object.__setattr__(self, "definitions", MappingProxyType(ordered))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def get(self, name: str) -> AgentDefinition | None:
        return self.definitions.get(name)


class AgentDefinitionError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        source: AgentDefinitionSource | None = None,
    ) -> None:
        self.source = source
        safe = " ".join(str(message).splitlines())
        super().__init__(safe[:MAX_DIAGNOSTIC_CHARS])


class AgentCatalogError(ValueError):
    pass


class SubagentKind(StrEnum):
    DEFINED = "defined"
    FORK = "fork"


class SubagentTaskStatus(StrEnum):
    REGISTERED = "registered"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            SubagentTaskStatus.COMPLETED,
            SubagentTaskStatus.FAILED,
            SubagentTaskStatus.CANCELLED,
        }

    @property
    def active(self) -> bool:
        return not self.terminal


class SubagentPlacement(StrEnum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


class TaskCancelResult(StrEnum):
    REQUESTED = "requested"
    NOT_FOUND = "not_found"
    ALREADY_TERMINAL = "already_terminal"
    ALREADY_REQUESTED = "already_requested"


@dataclass(frozen=True)
class SubagentParent:
    run_id: str
    iteration: int


@dataclass(frozen=True)
class SubagentProgress:
    iteration: int
    phase: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", self.message[:1024])


@dataclass(frozen=True)
class WorktreeTaskSummary:
    state: str
    path: str
    branch_ref: str
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path[:1024])
        object.__setattr__(self, "branch_ref", self.branch_ref[:256])
        if self.reason is not None:
            object.__setattr__(self, "reason", self.reason[:MAX_DIAGNOSTIC_CHARS])


@dataclass(frozen=True)
class SubagentTaskSnapshot:
    task_id: str
    kind: SubagentKind
    status: SubagentTaskStatus
    placement: SubagentPlacement
    role: str | None
    profile_name: str
    parent: SubagentParent
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: SubagentProgress | None = None
    result: str = ""
    error: str | None = None
    truncated: bool = False
    usage: TokenUsage = TokenUsage.zero()
    notification_pending: bool = False
    worktree: WorktreeTaskSummary | None = None


@dataclass(frozen=True)
class SubagentNotification:
    task_id: str
    status: SubagentTaskStatus
    role: str | None
    result: str
    error: str | None
    truncated: bool
    usage: TokenUsage
    completed_at: datetime
    worktree: WorktreeTaskSummary | None = None


@dataclass(frozen=True)
class NotificationBatch:
    notifications: tuple[SubagentNotification, ...]
    rendered_system_section: str
    encoded_bytes: int


@dataclass(frozen=True)
class SubagentTerminalEvent:
    task_id: str
    status: SubagentTaskStatus
    summary: str


@dataclass(frozen=True)
class SubagentDiagnostic:
    task_id: str | None
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", self.message[:MAX_DIAGNOSTIC_CHARS])
