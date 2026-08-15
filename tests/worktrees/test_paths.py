from pathlib import Path

import pytest

from mewcode.worktrees.models import RepositoryIdentity, WorktreeValidationError
from mewcode.worktrees.paths import WorktreeNameFactory, WorktreePathPolicy


@pytest.mark.parametrize("value", ["agent", "task/0123456789abcdef0123456789abcdef", "a.b_c-d"])
def test_valid_names(value: str) -> None:
    assert WorktreePathPolicy().parse_name(value).value == value


@pytest.mark.parametrize(
    "value",
    ["", "A", ".", "..", "a//b", "/a", "a\\b", "C:/x", "a/../b", "con", "a" * 33, "a\x00b"],
)
def test_unsafe_names(value: str) -> None:
    with pytest.raises(WorktreeValidationError):
        WorktreePathPolicy().parse_name(value)


def test_task_name_is_safe_and_layout_is_contained(tmp_path: Path) -> None:
    workspace = (tmp_path / "repo").resolve()
    common = (workspace / ".git").resolve()
    workspace.mkdir()
    common.mkdir()
    repository = RepositoryIdentity(workspace, common, "repo-1")
    name = WorktreeNameFactory().for_task("external/unsafe task")
    layout = WorktreePathPolicy().layout(repository, name)
    assert name.value.startswith("task/")
    assert layout.root.is_relative_to(workspace / ".mewcode" / "worktrees")
    assert layout.record_path.is_relative_to(common / "mewcode" / "worktrees")
    assert layout.branch_ref.endswith(name.value)


def test_link_ancestor_is_rejected(tmp_path: Path) -> None:
    workspace = (tmp_path / "repo").resolve()
    common = (workspace / ".git").resolve()
    workspace.mkdir()
    common.mkdir()
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    managed_parent = workspace / ".mewcode"
    try:
        managed_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are not available")
    repository = RepositoryIdentity(workspace, common, "repo-1")
    layout = WorktreePathPolicy().layout(repository, WorktreePathPolicy().parse_name("agent"))
    with pytest.raises(WorktreeValidationError):
        WorktreePathPolicy().validate_ancestors(layout)
