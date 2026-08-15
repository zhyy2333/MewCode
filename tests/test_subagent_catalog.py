from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from mewcode.permissions import PermissionMode
from mewcode.subagents import (
    FOREGROUND_TIMEOUT_SECONDS,
    MAX_ACTIVE_TASKS,
    MAX_CANDIDATES_PER_ROOT,
    MAX_DEFINITION_FILE_BYTES,
    MAX_DEFINITION_TURNS,
    MAX_NOTIFICATION_BATCH,
    MAX_NOTIFICATION_BYTES,
    MAX_RESULT_CHARS,
    MAX_RETAINED_TASKS,
    MAX_SELECTED_PROMPT_BYTES,
    MAX_TASK_BYTES,
    TASK_CLOSE_TIMEOUT_SECONDS,
    AgentCatalogError,
    AgentDefinition,
    AgentDefinitionCatalog,
    AgentDefinitionLayer,
    AgentDefinitionRoots,
    AgentDefinitionSource,
    build_agent_catalog,
    discover_agent_sources,
)


def _write(
    root: Path,
    name: str,
    body: str,
    *,
    tools: str = "[read_file]",
    disallowed: str = "[]",
    model: str = "inherit",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.md"
    path.write_text(
        "\n".join(
            (
                "---",
                f"name: {name}",
                f"description: {name} role",
                f"tools: {tools}",
                f"disallowed_tools: {disallowed}",
                f"model: {model}",
                "max_turns: 20",
                "permission_mode: default",
                "---",
                body,
            )
        ),
        encoding="utf-8",
    )
    return path


def _catalog(roots: AgentDefinitionRoots, **kwargs):
    return build_agent_catalog(
        discover_agent_sources(roots),
        profile_names=kwargs.get("profiles", {"main", "sonnet"}),
        base_tool_names=kwargs.get("tools", {"read_file", "write_file", "agent"}),
        globally_forbidden_names={"agent", "load_skill"},
    )


def test_models_are_immutable_sorted_and_limits_match_product_defaults(tmp_path: Path) -> None:
    source = AgentDefinitionSource(AgentDefinitionLayer.PLUGIN, tmp_path, tmp_path / "z.md", "z", "plugin:0")
    definition = AgentDefinition("z", "z", (), (), "inherit", 1, PermissionMode.DEFAULT, "body", source)
    catalog = AgentDefinitionCatalog({"z": definition, "a": definition})
    assert list(catalog.definitions) == ["a", "z"]
    assert isinstance(catalog.definitions, MappingProxyType)
    with pytest.raises(TypeError):
        catalog.definitions["x"] = definition  # type: ignore[index]
    assert list(AgentDefinitionLayer) == [
        AgentDefinitionLayer.PLUGIN,
        AgentDefinitionLayer.BUILTIN,
        AgentDefinitionLayer.USER,
        AgentDefinitionLayer.PROJECT,
    ]
    assert MAX_DEFINITION_FILE_BYTES == MAX_TASK_BYTES == MAX_NOTIFICATION_BYTES == 64 * 1024
    assert MAX_CANDIDATES_PER_ROOT == 256
    assert MAX_SELECTED_PROMPT_BYTES == 1024 * 1024
    assert MAX_RESULT_CHARS == 20_000
    assert MAX_ACTIVE_TASKS == 8
    assert MAX_NOTIFICATION_BATCH == 16
    assert MAX_RETAINED_TASKS == 128
    assert TASK_CLOSE_TIMEOUT_SECONDS == 5.0
    assert FOREGROUND_TIMEOUT_SECONDS == 10.0
    assert MAX_DEFINITION_TURNS == 100


def test_project_overrides_all_layers_and_snapshot_does_not_reread(tmp_path: Path) -> None:
    roots = AgentDefinitionRoots(
        tmp_path / "project",
        tmp_path / "user",
        tmp_path / "builtin",
        (tmp_path / "plugin",),
    )
    for root, body in (
        (roots.plugins[0], "plugin"),
        (roots.builtin, "builtin"),
        (roots.user, "user"),
        (roots.project, "project"),
    ):
        _write(root, "reviewer", body)
    catalog = _catalog(roots)
    assert catalog.definitions["reviewer"].system_prompt == "project"
    (roots.project / "reviewer.md").write_text("changed", encoding="utf-8")
    assert catalog.definitions["reviewer"].system_prompt == "project"


def test_invalid_higher_layers_fall_back_and_preserve_diagnostics(tmp_path: Path) -> None:
    roots = AgentDefinitionRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.builtin, "reviewer", "builtin")
    _write(roots.user, "reviewer", "user", model="missing")
    _write(roots.project, "reviewer", "project", tools="[unknown]")
    catalog = _catalog(roots)
    assert catalog.definitions["reviewer"].system_prompt == "builtin"
    assert len(catalog.diagnostics) == 2
    assert {diagnostic.source.layer for diagnostic in catalog.diagnostics} == {
        AgentDefinitionLayer.PROJECT,
        AgentDefinitionLayer.USER,
    }


def test_all_invalid_hides_role_without_affecting_other_role(tmp_path: Path) -> None:
    roots = AgentDefinitionRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "broken", "bad", model="missing")
    _write(roots.project, "valid", "good")
    catalog = _catalog(roots)
    assert list(catalog.definitions) == ["valid"]
    assert catalog.diagnostics[0].name == "broken"


def test_same_layer_valid_conflict_is_fatal_even_below_override(tmp_path: Path) -> None:
    roots = AgentDefinitionRoots(
        tmp_path / "p",
        tmp_path / "u",
        tmp_path / "b",
        (tmp_path / "plugin-a", tmp_path / "plugin-b"),
    )
    _write(roots.project, "reviewer", "project")
    _write(roots.plugins[0], "reviewer", "plugin-a")
    _write(roots.plugins[1], "reviewer", "plugin-b")
    with pytest.raises(AgentCatalogError, match="Conflicting valid"):
        _catalog(roots)


def test_same_layer_one_invalid_one_valid_selects_valid(tmp_path: Path) -> None:
    roots = AgentDefinitionRoots(
        tmp_path / "p",
        tmp_path / "u",
        tmp_path / "b",
        (tmp_path / "plugin-a", tmp_path / "plugin-b"),
    )
    _write(roots.plugins[0], "reviewer", "valid")
    _write(roots.plugins[1], "reviewer", "invalid", model="missing")
    catalog = _catalog(roots)
    assert catalog.definitions["reviewer"].system_prompt == "valid"
    assert len(catalog.diagnostics) == 1


@pytest.mark.parametrize(
    ("tools", "disallowed", "model", "message"),
    [
        ("[unknown]", "[]", "inherit", "Unknown agent tool"),
        ("[agent]", "[]", "inherit", "globally forbidden"),
        ("[read_file]", "[unknown]", "inherit", "Unknown agent tool"),
        ("[read_file]", "[]", "missing", "Unknown Profile"),
    ],
)
def test_semantic_validation_rejects_profiles_and_tools(
    tmp_path: Path,
    tools: str,
    disallowed: str,
    model: str,
    message: str,
) -> None:
    roots = AgentDefinitionRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "reviewer", "body", tools=tools, disallowed=disallowed, model=model)
    catalog = _catalog(roots)
    assert "reviewer" not in catalog.definitions
    assert message in catalog.diagnostics[0].message


def test_selected_prompt_total_limit_is_enforced_after_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import mewcode.subagents.catalog as catalog_module

    roots = AgentDefinitionRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "first", "12345")
    _write(roots.project, "second", "67890")
    monkeypatch.setattr(catalog_module, "MAX_SELECTED_PROMPT_BYTES", 9)

    with pytest.raises(AgentCatalogError, match="exceed 9 bytes"):
        _catalog(roots)

    monkeypatch.setattr(catalog_module, "MAX_SELECTED_PROMPT_BYTES", 10)
    assert list(_catalog(roots).definitions) == ["first", "second"]


def test_default_builtin_root_loads_read_only_explore_role(tmp_path: Path) -> None:
    roots = AgentDefinitionRoots.defaults(tmp_path)
    catalog = build_agent_catalog(
        discover_agent_sources(roots),
        profile_names={"main"},
        base_tool_names={
            "read_file",
            "find_files",
            "search_code",
            "write_file",
        },
    )
    explore = catalog.definitions["explore"]
    assert explore.source.layer is AgentDefinitionLayer.BUILTIN
    assert explore.tools == ("read_file", "find_files", "search_code")
    assert explore.model == "inherit"
    assert explore.permission_mode is PermissionMode.ALLOW
    assert "read-only codebase investigator" in explore.system_prompt
