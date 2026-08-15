from __future__ import annotations

from .base import ToolRegistry
from .command_tool import RunCommandTool
from .file_tools import EditFileTool, ReadFileTool, WriteFileTool
from .search_tools import FindFilesTool, SearchCodeTool
from .workspace import Workspace
from typing import Mapping


def create_builtin_registry(
    workspace: Workspace,
    *,
    process_environment: Mapping[str, str] | None = None,
) -> ToolRegistry:
    return ToolRegistry(
        [
            ReadFileTool(workspace),
            WriteFileTool(workspace),
            EditFileTool(workspace),
            RunCommandTool(workspace, process_environment=process_environment),
            FindFilesTool(workspace),
            SearchCodeTool(workspace),
        ]
    )
