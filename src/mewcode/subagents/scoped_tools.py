from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path, PurePath
from typing import Any

from mewcode.tools import Tool, ToolRegistry, ToolResult


@dataclass(frozen=True)
class FileReadObservation:
    path: str
    content_digest: str
    bytes_read: int


@dataclass
class FileReadObservationCache:
    observations: dict[str, FileReadObservation] = field(default_factory=dict)
    workspace_root: Path | None = None

    def observe(self, path: str, content: str) -> None:
        normalized = self._normalize(path)
        encoded = content.encode("utf-8")
        self.observations[normalized] = FileReadObservation(
            normalized,
            sha256(encoded).hexdigest(),
            len(encoded),
        )

    def invalidate(self, path: str) -> None:
        self.observations.pop(self._normalize(path), None)

    def _normalize(self, path: str) -> str:
        candidate = Path(path)
        if not candidate.is_absolute() and self.workspace_root is not None:
            candidate = self.workspace_root / candidate
        if candidate.is_absolute():
            value = str(candidate.resolve(strict=False))
            return os.path.normcase(value).casefold() if os.name == "nt" else value
        return _normalize_path(path)


class TaskScopedTool:
    def __init__(self, tool: Tool, observations: FileReadObservationCache) -> None:
        self._tool = tool
        self._observations = observations
        self.name = tool.name
        self.description = tool.description
        self.parameters_schema = tool.parameters_schema
        self.safety = tool.safety
        self.permission_spec = tool.permission_spec

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        result = await self._tool.execute(arguments)
        if not result.ok:
            return result
        path_value = result.metadata.get("path", arguments.get("path"))
        if not isinstance(path_value, str) or not path_value:
            return result
        if self.name == "read_file":
            self._observations.observe(path_value, result.content)
        elif self.name in {"write_file", "edit_file"}:
            self._observations.invalidate(path_value)
        return result


def build_task_scoped_registry(
    registry: ToolRegistry,
    observations: FileReadObservationCache,
) -> ToolRegistry:
    return ToolRegistry(TaskScopedTool(tool, observations) for tool in registry.list())


def _normalize_path(path: str) -> str:
    return PurePath(path.translate({ord("\\"): ord("/")})).as_posix()
