from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from .models import RepositoryIdentity, WorktreeLayout, WorktreeName, WorktreeValidationError


MAX_NAME_LENGTH = 96
MAX_SEGMENT_LENGTH = 32
_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _canonical_path(path: Path) -> str:
    value = str(path.resolve(strict=False))
    return os.path.normcase(value).casefold()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if path.is_symlink():
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def is_link_or_reparse(path: Path) -> bool:
    return _is_reparse_point(path)


class WorktreeNameFactory:
    def for_task(self, task_id: str) -> WorktreeName:
        if not task_id:
            raise WorktreeValidationError("Task ID must not be empty.")
        compact = task_id.replace("-", "").lower()
        token = compact if len(compact) == 32 and all(ch in "0123456789abcdef" for ch in compact) else hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]
        return WorktreePathPolicy().parse_name(f"task/{token}")


class WorktreePathPolicy:
    def parse_name(self, value: str) -> WorktreeName:
        if not isinstance(value, str) or not value or value != value.strip():
            raise WorktreeValidationError("Worktree name is empty or padded.")
        if len(value) > MAX_NAME_LENGTH or "\\" in value or value.startswith("/") or ":" in value:
            raise WorktreeValidationError("Worktree name uses unsafe path syntax.")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise WorktreeValidationError("Worktree name contains a control character.")
        parts = value.split("/")
        if any(not part or part in {".", ".."} or len(part) > MAX_SEGMENT_LENGTH for part in parts):
            raise WorktreeValidationError("Worktree name contains an invalid segment.")
        for part in parts:
            if not _SEGMENT.fullmatch(part):
                raise WorktreeValidationError("Worktree name contains invalid characters.")
            device = part.split(".", 1)[0].casefold()
            if device in _WINDOWS_RESERVED or part.endswith((".", " ")):
                raise WorktreeValidationError("Worktree name uses a reserved platform name.")
        canonical = "/".join(parts).casefold()
        return WorktreeName(value, canonical)

    def layout(self, repository: RepositoryIdentity, name: WorktreeName) -> WorktreeLayout:
        managed_root = repository.workspace_root / ".mewcode" / "worktrees"
        root = managed_root.joinpath(*name.value.split("/"))
        control_root = repository.common_dir / "mewcode" / "worktrees"
        record_base = control_root.joinpath("records", *name.value.split("/"))
        lock_base = control_root.joinpath("locks", *name.value.split("/"))
        record = record_base.with_name(record_base.name + ".json")
        lock = lock_base.with_name(lock_base.name + ".lock")
        marker = root / ".mewcode" / "worktree.json"
        if not _is_within(root, managed_root) or not _is_within(record, control_root) or not _is_within(lock, control_root):
            raise WorktreeValidationError("Derived Worktree layout escapes its managed root.")
        return WorktreeLayout(
            name,
            managed_root,
            root,
            f"refs/heads/mewcode/worktree/{name.value}",
            control_root,
            record,
            marker,
            lock,
        )

    def validate_ancestors(self, layout: WorktreeLayout) -> None:
        self._validate_chain(layout.managed_root.parent, layout.root.parent)
        self._validate_chain(layout.control_root.parent, layout.record_path.parent)
        existing = layout.root
        if existing.exists() and _is_reparse_point(existing):
            raise WorktreeValidationError("Managed Worktree target is a link or reparse point.")

    def validate_delete_target(self, layout: WorktreeLayout) -> None:
        root = layout.root.resolve(strict=False)
        if _canonical_path(root) != _canonical_path(layout.root):
            raise WorktreeValidationError("Worktree target changed during validation.")
        if not _is_within(root, layout.managed_root.resolve(strict=False)) or root == layout.managed_root.resolve(strict=False):
            raise WorktreeValidationError("Delete target is outside the managed Worktree root.")
        self.validate_ancestors(layout)

    @staticmethod
    def _validate_chain(start: Path, end: Path) -> None:
        start = Path(os.path.abspath(start))
        end = Path(os.path.abspath(end))
        if not _is_within(end, start):
            raise WorktreeValidationError("Path ancestry escapes the expected root.")
        current = start
        if current.exists() and _is_reparse_point(current):
            raise WorktreeValidationError("Managed path contains a link or reparse point.")
        for part in end.relative_to(start).parts:
            current = current / part
            if current.exists() and _is_reparse_point(current):
                raise WorktreeValidationError("Managed path contains a link or reparse point.")
