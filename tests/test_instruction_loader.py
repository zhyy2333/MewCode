from pathlib import Path

import pytest

from mewcode.continuity import ContinuityPaths, InstructionLoader


def _paths(tmp_path: Path) -> ContinuityPaths:
    workspace = tmp_path / "workspace"
    user = tmp_path / "user"
    workspace.mkdir()
    user.mkdir()
    return ContinuityPaths.for_workspace(workspace, user_root=user)


def test_empty_and_single_instruction_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    loader = InstructionLoader()
    assert loader.load(paths).content == ""
    paths.project_root_instructions.write_bytes(b"one\r\ntwo\n")
    snapshot = loader.load(paths)
    assert snapshot.content == "### Project-root instructions\none\ntwo"
    assert snapshot.diagnostics == ()


def test_priority_and_startup_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.project_local_instructions.parent.mkdir()
    paths.project_local_instructions.write_text("local", encoding="utf-8")
    paths.project_root_instructions.write_text("root", encoding="utf-8")
    paths.user_instructions.write_text("user", encoding="utf-8")
    snapshot = InstructionLoader().load(paths)
    assert snapshot.content.index("local") < snapshot.content.index("root")
    assert snapshot.content.index("root") < snapshot.content.index("user")
    paths.project_local_instructions.write_text("changed", encoding="utf-8")
    assert "changed" not in snapshot.content
    assert "changed" in InstructionLoader().load(paths).content


def test_include_expands_in_place_and_supports_spaces(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    included = paths.workspace_root / "docs" / "shared rules.md"
    included.parent.mkdir()
    included.write_text("shared\n", encoding="utf-8")
    paths.project_root_instructions.write_text(
        "before\n@include docs/shared rules.md\nafter\n"
        "inline @include ignored.md\n",
        encoding="utf-8",
    )
    content = InstructionLoader().load(paths).content
    assert content.index("before") < content.index("shared") < content.index("after")
    assert "inline @include ignored.md" in content


def test_duplicate_cycle_and_depth_are_bounded(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.project_root_instructions.write_text(
        "@include a.md\n@include a.md\n",
        encoding="utf-8",
    )
    (paths.workspace_root / "a.md").write_text("A\n@include b.md\n", encoding="utf-8")
    (paths.workspace_root / "b.md").write_text("B\n@include a.md\n", encoding="utf-8")
    snapshot = InstructionLoader().load(paths)
    assert snapshot.content.count("\nA") == 1
    assert any(item.code == "include_repeated" for item in snapshot.diagnostics)

    paths.project_root_instructions.write_text("@include d1.md\n", encoding="utf-8")
    for index in range(1, 7):
        suffix = f"@include d{index + 1}.md\n" if index < 6 else "deep\n"
        (paths.workspace_root / f"d{index}.md").write_text(suffix, encoding="utf-8")
    snapshot = InstructionLoader().load(paths)
    assert "deep" not in snapshot.content
    assert any(item.code == "include_depth_exceeded" for item in snapshot.diagnostics)


def test_project_and_user_sandboxes_are_independent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.project_root_instructions.write_text("@include ../outside.md\n", encoding="utf-8")
    (tmp_path / "outside.md").write_text("secret-project", encoding="utf-8")
    paths.user_instructions.write_text("@include child.md\n", encoding="utf-8")
    (paths.user_root / "child.md").write_text("user-child", encoding="utf-8")
    snapshot = InstructionLoader().load(paths)
    assert "secret-project" not in snapshot.content
    assert "user-child" in snapshot.content
    assert any(item.code == "include_outside_scope" for item in snapshot.diagnostics)


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    link = paths.workspace_root / "linked.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    paths.project_root_instructions.write_text("@include linked.md\n", encoding="utf-8")
    snapshot = InstructionLoader().load(paths)
    assert "outside-secret" not in snapshot.content
    assert any(item.code == "include_outside_scope" for item in snapshot.diagnostics)
