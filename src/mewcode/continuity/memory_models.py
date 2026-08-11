from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re


NOTE_ID_PATTERN = re.compile(r"^mem-[a-z0-9]{6,64}$")


class MemoryScope(StrEnum):
    PROJECT = "project"
    USER = "user"


class MemoryCategory(StrEnum):
    USER_PREFERENCE = "user_preference"
    CORRECTION = "correction"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE = "reference"


class MemoryAction(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True)
class MemoryConfig:
    index_max_lines: int = 200
    index_max_bytes: int = 25 * 1024
    summary_max_chars: int = 240
    note_max_bytes: int = 8 * 1024
    max_mutations: int = 16
    update_max_output_tokens: int = 4096
    update_context_tokens: int = 128_000

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class MemoryNote:
    version: int
    note_id: str
    scope: MemoryScope
    category: MemoryCategory
    summary: str
    body: str
    priority: int
    created_at: datetime
    updated_at: datetime
    source_session_id: str

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError("unsupported memory note version")
        if not NOTE_ID_PATTERN.fullmatch(self.note_id):
            raise ValueError("invalid memory note id")
        if not self.summary.strip() or not self.body.strip():
            raise ValueError("memory note text must not be empty")
        if self.priority not in range(1, 6):
            raise ValueError("memory priority must be between 1 and 5")
        _aware(self.created_at)
        _aware(self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("memory update time precedes creation time")
        if not self.source_session_id.strip():
            raise ValueError("source session id must not be empty")


@dataclass(frozen=True)
class MemoryIndexEntry:
    note_id: str
    scope: MemoryScope
    category: MemoryCategory
    summary: str
    priority: int
    updated_at: datetime
    relative_path: str

    def __post_init__(self) -> None:
        if not NOTE_ID_PATTERN.fullmatch(self.note_id):
            raise ValueError("invalid memory index id")
        if not self.summary.strip():
            raise ValueError("memory index summary must not be empty")
        if self.priority not in range(1, 6):
            raise ValueError("memory priority must be between 1 and 5")
        _aware(self.updated_at)
        if self.relative_path != f"notes/{self.note_id}.md":
            raise ValueError("memory index path does not match its id")


@dataclass(frozen=True)
class MemoryPromptView:
    content: str = ""
    lines: int = 0
    bytes: int = 0
    included_note_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryTurn:
    session_id: str
    user_text: str
    assistant_final_text: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session id must not be empty")
        _aware(self.occurred_at)


@dataclass(frozen=True)
class MemoryMutation:
    action: MemoryAction
    scope: MemoryScope
    note_id: str | None = None
    category: MemoryCategory | None = None
    summary: str | None = None
    body: str | None = None
    priority: int | None = None

    def __post_init__(self) -> None:
        if self.note_id is not None and not NOTE_ID_PATTERN.fullmatch(self.note_id):
            raise ValueError("invalid memory mutation id")
        if self.action is MemoryAction.DELETE:
            if self.note_id is None:
                raise ValueError("delete requires a note id")
            if any(value is not None for value in (self.category, self.summary, self.body, self.priority)):
                raise ValueError("delete accepts only scope and note id")
            return
        if any(value is None for value in (self.category, self.summary, self.body, self.priority)):
            raise ValueError("upsert requires category, summary, body, and priority")
        if not (self.summary or "").strip() or not (self.body or "").strip():
            raise ValueError("upsert text must not be empty")
        if self.priority not in range(1, 6):
            raise ValueError("memory priority must be between 1 and 5")


@dataclass(frozen=True)
class MemoryUpdatePlan:
    version: int
    mutations: tuple[MemoryMutation, ...]

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError("unsupported memory update version")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("memory timestamps must be timezone-aware")
