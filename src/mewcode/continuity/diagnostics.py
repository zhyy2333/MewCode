from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContinuityComponent(StrEnum):
    INSTRUCTIONS = "instructions"
    SESSION = "session"
    MEMORY = "memory"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ContinuityDiagnostic:
    component: ContinuityComponent
    code: str
    severity: DiagnosticSeverity
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("diagnostic code must not be empty")
        if not self.message.strip():
            raise ValueError("diagnostic message must not be empty")


class ContinuityError(RuntimeError):
    pass


class InstructionError(ContinuityError):
    pass


class SessionError(ContinuityError):
    pass


class SessionPersistenceError(SessionError):
    pass


class MemoryError(ContinuityError):
    pass
