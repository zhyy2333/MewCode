from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())

    def resolve_path(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise WorkspaceError("Path must be a non-empty string.")

        raw_path = Path(path)
        candidate = raw_path if raw_path.is_absolute() else self.root / raw_path
        resolved = candidate.resolve()
        if not _is_relative_to(resolved, self.root):
            raise WorkspaceError(f"Path is outside the workspace: {path}")
        return resolved

    def relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        if not _is_relative_to(resolved, self.root):
            raise WorkspaceError(f"Path is outside the workspace: {path}")
        return resolved.relative_to(self.root).as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
