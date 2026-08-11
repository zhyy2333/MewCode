from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContinuityPaths:
    workspace_root: Path
    user_root: Path
    project_local_instructions: Path
    project_root_instructions: Path
    user_instructions: Path
    sessions_root: Path
    project_memory_root: Path
    user_memory_root: Path

    @classmethod
    def for_workspace(
        cls,
        workspace_root: Path,
        *,
        user_root: Path | None = None,
    ) -> ContinuityPaths:
        workspace = workspace_root.resolve()
        user = (user_root or (Path.home() / ".mewcode")).resolve()
        project_private = workspace / ".mewcode"
        return cls(
            workspace_root=workspace,
            user_root=user,
            project_local_instructions=project_private / "instructions.md",
            project_root_instructions=workspace / "MEWCODE.md",
            user_instructions=user / "instructions.md",
            sessions_root=project_private / "sessions",
            project_memory_root=project_private / "memory",
            user_memory_root=user / "memory",
        )
