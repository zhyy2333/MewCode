from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath


GLOB_META = "*?["


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

    def normalize_glob(self, pattern: str) -> str:
        if not isinstance(pattern, str) or not pattern.strip():
            raise WorkspaceError("Pattern must be a non-empty string.")

        normalized = pattern.strip()
        if os.name == "nt":
            normalized = normalized.replace("\\", "/")
        if PurePosixPath(normalized).is_absolute() or PureWindowsPath(
            normalized
        ).is_absolute():
            raise WorkspaceError(f"Glob pattern is outside the workspace: {pattern}")

        parts = normalized.split("/")
        if any(part == ".." for part in parts):
            raise WorkspaceError(f"Glob pattern is outside the workspace: {pattern}")
        clean_parts = [part for part in parts if part not in {"", "."}]
        if not clean_parts:
            raise WorkspaceError("Pattern must be a non-empty string.")

        fixed_parts: list[str] = []
        for part in clean_parts:
            if any(character in part for character in GLOB_META):
                break
            fixed_parts.append(part)
        fixed_prefix = "/".join(fixed_parts) if fixed_parts else "."
        self.resolve_path(fixed_prefix)
        return "/".join(clean_parts)

    def validate_match(self, path: Path) -> str:
        return self.relative_path(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
