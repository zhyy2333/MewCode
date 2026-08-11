from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from mewcode.providers import ChatMessage

from .diagnostics import ContinuityDiagnostic

if TYPE_CHECKING:
    from .session_repository import SessionBinding


class SessionOpenMode(StrEnum):
    AUTO = "auto"
    NEW = "new"
    RESUME = "resume"


@dataclass(frozen=True)
class SessionOpenRequest:
    mode: SessionOpenMode = SessionOpenMode.AUTO
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode is SessionOpenMode.RESUME and not (self.session_id or "").strip():
            raise ValueError("resume mode requires a session id")
        if self.mode is not SessionOpenMode.RESUME and self.session_id is not None:
            raise ValueError("session id is only valid in resume mode")


@dataclass(frozen=True)
class StoredPlan:
    task: str
    text: str


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    title: str
    message_count: int
    last_activity: datetime
    recoverable: bool
    invalid_lines: int = 0


@dataclass(frozen=True)
class SessionState:
    session_id: str
    messages: tuple[ChatMessage, ...] = ()
    pending_plan: StoredPlan | None = None
    last_activity: datetime | None = None


@dataclass(frozen=True)
class SessionOpenResult:
    binding: SessionBinding
    state: SessionState
    diagnostics: tuple[ContinuityDiagnostic, ...] = ()


@dataclass(frozen=True)
class SessionReplay:
    session_id: str
    messages: tuple[ChatMessage, ...]
    pending_plan: StoredPlan | None
    created_at: datetime | None
    last_activity: datetime | None
    invalid_lines: int
    partial_offset: int | None
    valid_start: bool

    @property
    def recoverable(self) -> bool:
        return self.valid_start and self.last_activity is not None
