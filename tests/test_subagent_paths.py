from __future__ import annotations

import os
from pathlib import Path

import pytest

from mewcode.subagents import (
    MAX_CANDIDATES_PER_ROOT,
    AgentDefinitionError,
    AgentDefinitionLayer,
    AgentDefinitionRoots,
    discover_agent_sources,
)


def test_default_roots_and_four_layer_discovery(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    roots = AgentDefinitionRoots.defaults(tmp_path, (plugin,))
    assert roots.project == tmp_path.resolve() / ".mewcode" / "agents"
    assert roots.user.name == "agents"
    assert roots.builtin.name == "builtin"
    assert roots.plugins == (plugin.resolve(),)

    custom = AgentDefinitionRoots(
        tmp_path / "project",
        tmp_path / "user",
        tmp_path / "builtin",
        (plugin,),
    )
    for root, name in (
        (custom.project, "zeta.md"),
        (custom.user, "alpha.md"),
        (custom.builtin, "beta.md"),
        (plugin, "gamma.md"),
    ):
        root.mkdir(parents=True)
        (root / name).write_text("x", encoding="utf-8")
        (root / "ignored.txt").write_text("x", encoding="utf-8")
        (root / "nested").mkdir()
        (root / "nested" / "hidden.md").write_text("x", encoding="utf-8")

    sources = discover_agent_sources(custom)
    assert [source.layer for source in sources] == [
        AgentDefinitionLayer.PROJECT,
        AgentDefinitionLayer.USER,
        AgentDefinitionLayer.BUILTIN,
        AgentDefinitionLayer.PLUGIN,
    ]
    assert [source.entry_name for source in sources] == ["zeta", "alpha", "beta", "gamma"]
    assert [source.origin for source in sources] == ["project", "user", "builtin", "plugin:0"]


def test_missing_root_is_ignored_and_file_root_is_rejected(tmp_path: Path) -> None:
    file_root = tmp_path / "file"
    file_root.write_text("x", encoding="utf-8")
    roots = AgentDefinitionRoots(file_root, tmp_path / "none", tmp_path / "missing")
    with pytest.raises(AgentDefinitionError, match="not a directory"):
        discover_agent_sources(roots)


def test_candidate_limit_is_checked_per_plugin_root(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for index in range(MAX_CANDIDATES_PER_ROOT):
        (first / f"a-{index:03}.md").write_text("x", encoding="utf-8")
        (second / f"b-{index:03}.md").write_text("x", encoding="utf-8")
    roots = AgentDefinitionRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b", (first, second))
    assert len(discover_agent_sources(roots)) == MAX_CANDIDATES_PER_ROOT * 2
    (second / "overflow.md").write_text("x", encoding="utf-8")
    with pytest.raises(AgentDefinitionError, match="exceeds 256"):
        discover_agent_sources(roots)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_symlink_candidate_is_returned_as_a_safe_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = tmp_path / "target.md"
    target.write_text("secret", encoding="utf-8")
    link = root / "linked.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not permitted")
    roots = AgentDefinitionRoots(root, tmp_path / "u", tmp_path / "b")
    source = discover_agent_sources(roots)[0]
    assert source.path == link.absolute()
    assert "Symbolic-link" in (source.error or "")
