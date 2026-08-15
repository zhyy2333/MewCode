from __future__ import annotations

from collections.abc import Mapping

from .base import ToolRegistry
from .builtin import create_builtin_registry
from .workspace import Workspace


class WorkspaceToolBinder:
    """Rebuild a frozen tool selection for one explicit workspace."""

    def bind(
        self,
        frozen: ToolRegistry,
        workspace: Workspace,
        *,
        process_environment: Mapping[str, str],
        additional: ToolRegistry | None = None,
    ) -> ToolRegistry:
        available = create_builtin_registry(
            workspace,
            process_environment=process_environment,
        )
        if additional is not None:
            available = available.merge(additional)
        selected = []
        for name in frozen.names:
            tool = available.get(name)
            if tool is None:
                original = frozen.get(name)
                rebinder = getattr(original, "rebind_workspace", None)
                if not callable(rebinder):
                    raise RuntimeError(
                        f"Frozen tool '{name}' cannot be safely rebuilt for the Worktree."
                    )
                tool = rebinder(workspace.root, process_environment)
            selected.append(tool)
        return ToolRegistry(selected)
