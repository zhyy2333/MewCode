from __future__ import annotations

import os
from pathlib import Path

import pytest

from mewcode.tools.workspace import Workspace, WorkspaceError


def test_resolve_relative_path_inside_workspace(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    assert workspace.resolve_path("src/file.txt") == (tmp_path / "src/file.txt").resolve()


def test_resolve_absolute_path_inside_workspace(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    inside = tmp_path / "file.txt"

    assert workspace.resolve_path(str(inside)) == inside.resolve()


def test_rejects_empty_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspaceError, match="non-empty"):
        workspace.resolve_path("")


def test_rejects_parent_traversal_outside_workspace(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")

    with pytest.raises(WorkspaceError, match="outside"):
        workspace.resolve_path("../outside.txt")


def test_rejects_absolute_path_outside_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside.txt"
    workspace = Workspace(workspace_root)

    with pytest.raises(WorkspaceError, match="outside"):
        workspace.resolve_path(str(outside))


def test_relative_path_formats_inside_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    nested = tmp_path / "a" / "b.txt"
    nested.parent.mkdir()
    nested.write_text("x", encoding="utf-8")

    assert workspace.relative_path(nested) == "a/b.txt"


def test_relative_path_rejects_outside_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    workspace = Workspace(workspace_root)

    with pytest.raises(WorkspaceError, match="outside"):
        workspace.relative_path(outside)


@pytest.mark.skipif(
    os.name == "nt" and not hasattr(os, "symlink"),
    reason="symlink unavailable",
)
def test_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = workspace_root / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation not permitted")

    workspace = Workspace(workspace_root)

    with pytest.raises(WorkspaceError, match="outside"):
        workspace.resolve_path("link.txt")
