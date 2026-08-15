from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.worktrees.links import DirectoryLinker
from mewcode.worktrees.models import WorktreeValidationError


def test_directory_linker_creates_link_without_copying(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"payload")
    target = tmp_path / "nested" / "target"

    linker = DirectoryLinker()
    try:
        linker.create(source, target)
    except WorktreeValidationError as exc:
        pytest.skip(f"Directory links are unavailable on this platform: {exc}")

    assert target.is_symlink()
    assert (target / "large.bin").read_bytes() == b"payload"
    linker.remove(target)
    assert source.exists()
    assert not target.exists()


def test_directory_linker_rejects_files_and_existing_targets(tmp_path: Path) -> None:
    source_file = tmp_path / "file"
    source_file.write_text("x", encoding="utf-8")
    with pytest.raises(WorktreeValidationError):
        DirectoryLinker().create(source_file, tmp_path / "target")

    source_dir = tmp_path / "directory"
    source_dir.mkdir()
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(WorktreeValidationError):
        DirectoryLinker().create(source_dir, target)
