from __future__ import annotations

from pathlib import Path

from mewcode.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
from mewcode.tools.workspace import Workspace


def test_read_file_reads_workspace_file(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello", encoding="utf-8")
    result = ReadFileTool(Workspace(tmp_path)).execute({"path": "hello.txt"})

    assert result.ok is True
    assert result.content == "hello"
    assert result.metadata["path"] == "hello.txt"


def test_read_file_rejects_outside_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    result = ReadFileTool(Workspace(workspace_root)).execute({"path": str(outside)})

    assert result.ok is False
    assert "outside" in (result.error or "")


def test_read_file_truncates_large_content(tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    path.write_text("abcdef", encoding="utf-8")

    result = ReadFileTool(Workspace(tmp_path), content_limit=3).execute({"path": "big.txt"})

    assert result.ok is True
    assert result.content == "abc\n[truncated]"
    assert result.metadata["truncated"] is True


def test_write_file_writes_content_and_creates_parent(tmp_path: Path) -> None:
    result = WriteFileTool(Workspace(tmp_path)).execute(
        {"path": "nested/file.txt", "content": "hello"}
    )

    assert result.ok is True
    assert (tmp_path / "nested" / "file.txt").read_text(encoding="utf-8") == "hello"


def test_write_file_rejects_outside_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside.txt"

    result = WriteFileTool(Workspace(workspace_root)).execute(
        {"path": str(outside), "content": "no"}
    )

    assert result.ok is False
    assert not outside.exists()


def test_edit_file_replaces_unique_match(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("hello old world", encoding="utf-8")

    result = EditFileTool(Workspace(tmp_path)).execute(
        {"path": "file.txt", "old_text": "old", "new_text": "new"}
    )

    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "hello new world"


def test_edit_file_fails_when_match_missing(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    original = "hello world"
    path.write_text(original, encoding="utf-8")

    result = EditFileTool(Workspace(tmp_path)).execute(
        {"path": "file.txt", "old_text": "missing", "new_text": "new"}
    )

    assert result.ok is False
    assert result.metadata["matches"] == 0
    assert path.read_text(encoding="utf-8") == original


def test_edit_file_fails_when_match_is_not_unique(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    original = "old old"
    path.write_text(original, encoding="utf-8")

    result = EditFileTool(Workspace(tmp_path)).execute(
        {"path": "file.txt", "old_text": "old", "new_text": "new"}
    )

    assert result.ok is False
    assert result.metadata["matches"] == 2
    assert path.read_text(encoding="utf-8") == original


def test_edit_file_rejects_outside_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old", encoding="utf-8")

    result = EditFileTool(Workspace(workspace_root)).execute(
        {"path": str(outside), "old_text": "old", "new_text": "new"}
    )

    assert result.ok is False
    assert outside.read_text(encoding="utf-8") == "old"


def test_edit_file_rejects_empty_old_text(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("hello", encoding="utf-8")

    result = EditFileTool(Workspace(tmp_path)).execute(
        {"path": "file.txt", "old_text": "", "new_text": "new"}
    )

    assert result.ok is False
    assert "old_text" in (result.error or "")
