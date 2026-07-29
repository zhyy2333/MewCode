from __future__ import annotations

from typing import Any

from .base import (
    DEFAULT_TOOL_CONTENT_LIMIT,
    ToolResult,
    truncate_text,
)
from .workspace import Workspace, WorkspaceError


class ReadFileTool:
    name = "read_file"
    description = "Read a UTF-8 text file inside the current workspace."
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(
        self, workspace: Workspace, content_limit: int = DEFAULT_TOOL_CONTENT_LIMIT
    ) -> None:
        self._workspace = workspace
        self._content_limit = content_limit

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._workspace.resolve_path(arguments["path"])
            content = path.read_text(encoding="utf-8")
            content, truncated = truncate_text(content, self._content_limit)
            return ToolResult(
                ok=True,
                tool_name=self.name,
                content=content,
                metadata={
                    "path": self._workspace.relative_path(path),
                    "truncated": truncated,
                },
            )
        except (OSError, UnicodeError, WorkspaceError) as exc:
            return _failure(self.name, exc)


class WriteFileTool:
    name = "write_file"
    description = "Write UTF-8 text to a file inside the current workspace."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._workspace.resolve_path(arguments["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments["content"], encoding="utf-8")
            relative_path = self._workspace.relative_path(path)
            return ToolResult(
                ok=True,
                tool_name=self.name,
                content=f"Wrote {relative_path}",
                metadata={"path": relative_path, "bytes": len(arguments["content"].encode("utf-8"))},
            )
        except (OSError, UnicodeError, WorkspaceError) as exc:
            return _failure(self.name, exc)


class EditFileTool:
    name = "edit_file"
    description = "Replace exactly one occurrence of text in a UTF-8 file inside the workspace."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._workspace.resolve_path(arguments["path"])
            old_text = arguments["old_text"]
            new_text = arguments["new_text"]
            if old_text == "":
                return ToolResult(
                    ok=False,
                    tool_name=self.name,
                    content="",
                    error="old_text must not be empty.",
                    metadata={"path": self._workspace.relative_path(path)},
                )

            content = path.read_text(encoding="utf-8")
            count = content.count(old_text)
            if count != 1:
                relative_path = self._workspace.relative_path(path)
                return ToolResult(
                    ok=False,
                    tool_name=self.name,
                    content="",
                    error=f"old_text matched {count} times in {relative_path}; expected exactly 1.",
                    metadata={"path": relative_path, "matches": count},
                )

            path.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            relative_path = self._workspace.relative_path(path)
            return ToolResult(
                ok=True,
                tool_name=self.name,
                content=f"Edited {relative_path}",
                metadata={"path": relative_path, "matches": 1},
            )
        except (OSError, UnicodeError, WorkspaceError) as exc:
            return _failure(self.name, exc)


def _failure(tool_name: str, exc: Exception) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        content="",
        error=str(exc),
    )
