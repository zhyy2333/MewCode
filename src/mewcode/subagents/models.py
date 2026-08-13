from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from mewcode.permissions import PermissionMode


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
MAX_DEFINITION_TURNS = 100
MAX_DIAGNOSTIC_CHARS = 512


class AgentDefinitionLayer(IntEnum):
    PLUGIN = 0
    BUILTIN = 1
    USER = 2
    PROJECT = 3


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
