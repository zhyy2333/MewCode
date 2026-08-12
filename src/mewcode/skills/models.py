from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from mewcode.tools import ToolSafety

SKILL_NAME_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
TOOL_LOCAL_NAME_PATTERN = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
MAX_SKILLS_PER_LAYER = 256
MAX_PACKAGE_FILES = 512
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_FRONTMATTER_BYTES = 64 * 1024
MAX_SOP_BYTES = 128 * 1024
MAX_TOOLS_PER_SKILL = 64
MAX_TOOL_DECLARATION_BYTES = 64 * 1024
MAX_TOOL_WHITELIST = 128
MAX_DESCRIPTION_CHARS = 200
MAX_INPUT_BYTES = 64 * 1024
MAX_ACTIVE_SHARED_SOP_BYTES = 256 * 1024
MAX_COMMAND_ARGV = 64
MAX_COMMAND_ARG_CHARS = 4096
MAX_TOOL_STDIN_BYTES = 1024 * 1024
MAX_TOOL_STDOUT_BYTES = 1024 * 1024
MAX_TOOL_STDERR_BYTES = 64 * 1024
MAX_ISOLATED_DEPTH = 4
DEFAULT_TOOL_TIMEOUT_SECONDS = 60
MIN_TOOL_TIMEOUT_SECONDS = 1
MAX_TOOL_TIMEOUT_SECONDS = 600


class SkillLayer(IntEnum):
    BUILTIN = 0
    USER = 1
    PROJECT = 2


class SkillMode(StrEnum):
    SHARED = "shared"
    ISOLATED = "isolated"


@dataclass(frozen=True, order=True)
class FileStamp:
    relative_path: str
    kind: str
    size: int
    modified_ns: int
    file_id: int | None = None


@dataclass(frozen=True)
class SkillFingerprint:
    root: str
    files: tuple[FileStamp, ...]


@dataclass(frozen=True)
class SkillSource:
    layer: SkillLayer
    root: Path
    entry_path: Path
    package_dir: Path | None
    entry_name: str
    fingerprint: SkillFingerprint

    @property
    def label(self) -> str:
        return f"{self.layer.name.lower()}:{self.entry_path}"


@dataclass(frozen=True)
class SkillBodyRef:
    path: Path
    byte_offset: int
    byte_size: int
    fingerprint: SkillFingerprint


@dataclass(frozen=True)
class SkillToolDeclaration:
    local_name: str
    public_name: str
    description: str
    parameters: dict[str, Any]
    command: tuple[str, ...]
    safety: ToolSafety
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS
    source_path: Path | None = None


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    tools: tuple[str, ...]
    mode: SkillMode
    history: int | None
    model: str | None
    body: SkillBodyRef
    source: SkillSource
    package_tools: tuple[SkillToolDeclaration, ...] = ()

    @property
    def package_tool_names(self) -> frozenset[str]:
        return frozenset(tool.public_name for tool in self.package_tools)


@dataclass(frozen=True)
class SkillDiagnostic:
    source: str
    message: str


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    definitions: Mapping[str, SkillDefinition]
    diagnostics: tuple[SkillDiagnostic, ...] = ()
    fingerprint: tuple[SkillFingerprint, ...] = ()

    @classmethod
    def create(
        cls,
        definitions: Mapping[str, SkillDefinition],
        diagnostics: tuple[SkillDiagnostic, ...] = (),
        fingerprint: tuple[SkillFingerprint, ...] = (),
    ) -> SkillCatalogSnapshot:
        ordered = dict(sorted(definitions.items(), key=lambda item: item[0]))
        return cls(MappingProxyType(ordered), diagnostics, fingerprint)

    def get(self, name: str) -> SkillDefinition | None:
        return self.definitions.get(name)


class SkillDefinitionError(ValueError):
    pass


class SkillCatalogError(RuntimeError):
    pass
