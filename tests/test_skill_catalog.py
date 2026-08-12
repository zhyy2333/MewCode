from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.skills import (
    SkillCatalogError,
    SkillLayer,
    SkillRoots,
    build_skill_catalog,
    discover_sources,
)


def _skill(root: Path, name: str, description: str, tools: str = "[]") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ntools: {tools}\nmode: shared\n---\nBody",
        encoding="utf-8",
    )


def test_catalog_uses_highest_valid_layer_and_falls_back(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    _skill(roots.builtin, "sample", "builtin")
    _skill(roots.user, "sample", "user")
    _skill(roots.project, "sample", "project")
    catalog = build_skill_catalog(discover_sources(roots))
    assert catalog.get("sample").description == "project"

    (roots.project / "sample.md").write_text("invalid", encoding="utf-8")
    catalog = build_skill_catalog(discover_sources(roots))
    assert catalog.get("sample").description == "user"
    assert catalog.diagnostics


def test_same_layer_file_and_directory_duplicate_is_fatal(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _skill(root, "sample", "file")
    package = root / "sample"
    package.mkdir()
    (package / "SKILL.md").write_text(
        "---\nname: sample\ndescription: package\ntools: []\nmode: shared\n---\nBody",
        encoding="utf-8",
    )
    roots = SkillRoots(root, tmp_path / "user", tmp_path / "builtin")
    with pytest.raises(SkillCatalogError, match="Duplicate.*sample"):
        build_skill_catalog(discover_sources(roots))


def test_system_command_conflict_is_fatal(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _skill(root, "reset", "conflict")
    with pytest.raises(SkillCatalogError, match="reset"):
        build_skill_catalog(
            discover_sources(SkillRoots(root, tmp_path / "u", tmp_path / "b")),
            system_command_identifiers={"RESET"},
        )


def test_missing_and_cross_skill_tools_are_fatal(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _skill(root, "sample", "sample", "[missing_tool]")
    with pytest.raises(SkillCatalogError, match="missing_tool"):
        build_skill_catalog(
            discover_sources(SkillRoots(root, tmp_path / "u", tmp_path / "b")),
            global_tool_names={"read_file"},
        )


def test_missing_mcp_tool_reports_server_status(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _skill(root, "sample", "sample", "[remote__lookup]")
    with pytest.raises(SkillCatalogError) as caught:
        build_skill_catalog(
            discover_sources(SkillRoots(root, tmp_path / "u", tmp_path / "b")),
            global_tool_names={"read_file"},
            mcp_status={"remote": "failed to start"},
        )
    message = str(caught.value)
    assert "sample" in message
    assert "remote__lookup" in message
    assert "failed to start" in message


def test_package_static_error_is_isolated_as_definition_warning(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _skill(root, "valid", "valid")
    package = root / "broken"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: broken\ndescription: broken\ntools: []\nmode: shared\n---\nBody",
        encoding="utf-8",
    )
    link = package / "linked.txt"
    try:
        link.symlink_to(root / "valid.md")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    catalog = build_skill_catalog(
        discover_sources(SkillRoots(root, tmp_path / "u", tmp_path / "b"))
    )
    assert tuple(catalog.definitions) == ("valid",)
    assert catalog.diagnostics and "Symbolic" in catalog.diagnostics[0].message
