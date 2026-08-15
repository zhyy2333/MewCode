from __future__ import annotations

import os
from pathlib import Path

from .models import WorktreeValidationError
from .paths import is_link_or_reparse


class DirectoryLinker:
    def create(self, source: Path, target: Path) -> None:
        if is_link_or_reparse(source):
            raise WorktreeValidationError("Directory link source must be a real directory.")
        source = source.resolve(strict=True)
        if not source.is_dir() or is_link_or_reparse(source):
            raise WorktreeValidationError("Directory link source must be a real directory.")
        if target.exists() or target.is_symlink():
            raise WorktreeValidationError("Directory link target already exists.")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(source, target, target_is_directory=True)
        except OSError as exc:
            raise WorktreeValidationError("Directory link creation is unavailable.") from exc
        if not target.is_symlink():
            raise WorktreeValidationError("Directory link creation did not produce a link.")

    def remove(self, target: Path) -> None:
        if target.is_symlink():
            target.unlink()
