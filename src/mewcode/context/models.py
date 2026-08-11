from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from mewcode.providers import ChatMessage, ModelRequest, TokenUsage
from mewcode.tools import ToolExecution


@dataclass(frozen=True)
class ContextConfig:
    context_window: int
    single_tool_tokens: int = 8_000
    tool_batch_tokens: int = 12_000
    tool_preview_tokens: int = 1_000
    recent_tokens: int = 10_000
    recent_messages: int = 5
    automatic_margin: int = 13_000
    manual_margin: int = 3_000
    summary_max_output_tokens: int = 8_192
    failure_limit: int = 3

    def __post_init__(self) -> None:
        integer_fields = (
            "context_window",
            "single_tool_tokens",
            "tool_batch_tokens",
            "tool_preview_tokens",
            "recent_tokens",
            "recent_messages",
            "automatic_margin",
            "manual_margin",
            "summary_max_output_tokens",
            "failure_limit",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.context_window <= self.summary_max_output_tokens + self.automatic_margin:
            raise ValueError(
                "context_window must exceed summary_max_output_tokens plus "
                "automatic_margin"
            )
        if self.single_tool_tokens > self.tool_batch_tokens:
            raise ValueError("single_tool_tokens must not exceed tool_batch_tokens")
        if self.tool_preview_tokens > self.single_tool_tokens:
            raise ValueError("tool_preview_tokens must not exceed single_tool_tokens")


class ContextStatusKind(StrEnum):
    TOOL_ARCHIVED = "tool_archived"
    COMPACTION_STARTED = "compaction_started"
    COMPACTION_COMPLETED = "compaction_completed"
    NO_COMPACTION_NEEDED = "no_compaction_needed"
    COMPACTION_FAILED = "compaction_failed"
    CIRCUIT_OPEN = "circuit_open"
    CIRCUIT_RECOVERED = "circuit_recovered"
    CLEANUP_WARNING = "cleanup_warning"


@dataclass(frozen=True)
class ContextStatus:
    kind: ContextStatusKind
    message: str
    usage: TokenUsage = field(default_factory=TokenUsage.zero)


class ArchiveKind(StrEnum):
    TOOL_RESULT = "tool_result"
    HISTORY = "history"


@dataclass(frozen=True)
class ArchiveRecord:
    kind: ArchiveKind
    relative_path: str
    estimated_tokens: int
    sequence: int


@dataclass(frozen=True)
class CharacterMeasure:
    weighted_characters: int = 0

    def __post_init__(self) -> None:
        if self.weighted_characters < 0:
            raise ValueError("weighted_characters must not be negative")

    @property
    def estimated_tokens(self) -> int:
        return (self.weighted_characters + 3) // 4

    def add(self, other: CharacterMeasure) -> CharacterMeasure:
        return CharacterMeasure(self.weighted_characters + other.weighted_characters)


@dataclass(frozen=True)
class RequestFootprint:
    measure: CharacterMeasure
    message_count: int
    signature: str


@dataclass(frozen=True)
class TokenEstimate:
    input_tokens: int
    anchored: bool
    footprint: RequestFootprint


@dataclass(frozen=True)
class ToolCompactionResult:
    executions: tuple[ToolExecution, ...]
    archives: tuple[ArchiveRecord, ...]
    statuses: tuple[ContextStatus, ...]


@dataclass(frozen=True)
class HistorySelection:
    early: tuple[ChatMessage, ...]
    recent: tuple[ChatMessage, ...]
    can_compact: bool


@dataclass(frozen=True)
class HistoryCompactionResult:
    messages: tuple[ChatMessage, ...]
    archive: ArchiveRecord | None
    usage: TokenUsage = field(default_factory=TokenUsage.zero)
    changed: bool = False


class CompactionMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


@dataclass(frozen=True)
class ContextPreparation:
    request: ModelRequest | None
    messages: tuple[ChatMessage, ...]
    footprint: RequestFootprint | None
    usage: TokenUsage = field(default_factory=TokenUsage.zero)
    changed: bool = False
    error: str | None = None
    cancelled: bool = False


@dataclass
class CompactionCircuitBreaker:
    failure_limit: int = 3
    consecutive_failures: int = 0
    is_open: bool = False

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_limit:
            self.is_open = True

    def record_success(self) -> bool:
        recovered = self.is_open
        self.consecutive_failures = 0
        self.is_open = False
        return recovered


class ContextError(RuntimeError):
    pass


class ContextArchiveError(ContextError):
    pass


class ContextCapacityError(ContextError):
    pass


class ContextCompactionError(ContextError):
    pass
