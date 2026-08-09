from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from typing import Any

from .base import DEFAULT_TOOL_CONTENT_LIMIT, ToolResult, ToolSafety, truncate_text
from .workspace import Workspace, WorkspaceError

SKIP_DIRS = {".git", ".pytest_cache", "__pycache__"}
MAX_SEARCH_MATCHES = 100


class FindFilesTool:
    name = "find_files"
    description = "Find files inside the workspace using a glob pattern. Prefer this dedicated tool over a general command for file discovery."
    safety = ToolSafety.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    }

    def __init__(
        self, workspace: Workspace, content_limit: int = DEFAULT_TOOL_CONTENT_LIMIT
    ) -> None:
        self._workspace = workspace
        self._content_limit = content_limit

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return await _run_cancellable(self._execute_sync, arguments)

    def _execute_sync(
        self, arguments: dict[str, Any], stop_requested: threading.Event
    ) -> ToolResult:
        pattern = arguments["pattern"]
        if not pattern.strip():
            return ToolResult(ok=False, tool_name=self.name, content="", error="pattern must not be empty.")

        try:
            matches = sorted(
                self._workspace.relative_path(path)
                for path in self._workspace.root.glob(pattern)
                if _keep_path(path, self._workspace.root, stop_requested)
            )
            content, truncated = truncate_text("\n".join(matches), self._content_limit)
            return ToolResult(
                ok=True,
                tool_name=self.name,
                content=content,
                metadata={"matches": len(matches), "truncated": truncated},
            )
        except (OSError, WorkspaceError) as exc:
            return _failure(self.name, exc)


class SearchCodeTool:
    name = "search_code"
    description = "Search UTF-8 text files inside the workspace for a query string. Prefer this dedicated tool over a general command for code search."
    safety = ToolSafety.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["query"],
    }

    def __init__(
        self,
        workspace: Workspace,
        max_matches: int = MAX_SEARCH_MATCHES,
        content_limit: int = DEFAULT_TOOL_CONTENT_LIMIT,
    ) -> None:
        self._workspace = workspace
        self._max_matches = max_matches
        self._content_limit = content_limit

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return await _run_cancellable(self._execute_sync, arguments)

    def _execute_sync(
        self, arguments: dict[str, Any], stop_requested: threading.Event
    ) -> ToolResult:
        query = arguments["query"]
        if not query:
            return ToolResult(ok=False, tool_name=self.name, content="", error="query must not be empty.")

        try:
            search_root = self._workspace.root
            if "path" in arguments and arguments["path"]:
                search_root = self._workspace.resolve_path(arguments["path"])
                if not search_root.exists():
                    return ToolResult(
                        ok=False,
                        tool_name=self.name,
                        content="",
                        error=f"path does not exist: {arguments['path']}",
                    )

            results: list[str] = []
            total_matches = 0
            for file_path in _iter_files(search_root, self._workspace.root, stop_requested):
                _raise_if_cancelled(stop_requested)
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeError):
                    continue

                for line_number, line in enumerate(lines, start=1):
                    _raise_if_cancelled(stop_requested)
                    if query in line:
                        total_matches += 1
                        if len(results) < self._max_matches:
                            relative = self._workspace.relative_path(file_path)
                            snippet = line.strip()
                            results.append(f"{relative}:{line_number}: {snippet}")

            content = "\n".join(results)
            content, content_truncated = truncate_text(content, self._content_limit)
            truncated = content_truncated or total_matches > len(results)
            return ToolResult(
                ok=True,
                tool_name=self.name,
                content=content,
                metadata={
                    "matches": total_matches,
                    "returned": len(results),
                    "truncated": truncated,
                },
            )
        except (OSError, WorkspaceError) as exc:
            return _failure(self.name, exc)


def _iter_files(
    root: Path, workspace_root: Path, stop_requested: threading.Event
):
    _raise_if_cancelled(stop_requested)
    if root.is_file():
        if not _is_skipped(root, workspace_root):
            yield root
        return

    for path in root.rglob("*"):
        _raise_if_cancelled(stop_requested)
        if path.is_file() and not _is_skipped(path, workspace_root):
            yield path


def _keep_path(
    path: Path, workspace_root: Path, stop_requested: threading.Event
) -> bool:
    _raise_if_cancelled(stop_requested)
    return path.is_file() and not _is_skipped(path, workspace_root)


def _is_skipped(path: Path, workspace_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(workspace_root).parts
    except ValueError:
        return True
    return any(part in SKIP_DIRS or (part.startswith(".") and part not in {".", ".."}) for part in relative_parts[:-1])


def _failure(tool_name: str, exc: Exception) -> ToolResult:
    return ToolResult(ok=False, tool_name=tool_name, content="", error=str(exc))


class _SearchCancelled(Exception):
    pass


def _raise_if_cancelled(stop_requested: threading.Event) -> None:
    if stop_requested.is_set():
        raise _SearchCancelled("Search cancelled.")


async def _run_cancellable(worker, arguments: dict[str, Any]) -> ToolResult:
    stop_requested = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(worker, arguments, stop_requested))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        stop_requested.set()
        try:
            await task
        except _SearchCancelled:
            pass
        raise
