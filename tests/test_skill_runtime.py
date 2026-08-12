from __future__ import annotations

from pathlib import Path

from mewcode.continuity import StoredSkillActivation
from mewcode.skills import (
    SkillLayer,
    SkillRoots,
    SkillRuntime,
    build_skill_catalog,
    discover_sources,
)
from mewcode.tools import ToolRegistry


class Binding:
    def __init__(self): self.values = []
    def commit_skills(self, values): self.values.append(tuple(values))


def _write(root: Path, name: str, body: str, mode: str = "shared") -> None:
    root.mkdir(parents=True, exist_ok=True)
    history = "\nhistory: 0" if mode == "isolated" else ""
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\ntools: []\nmode: {mode}{history}\n---\n{body}",
        encoding="utf-8",
    )


def _catalog(roots: SkillRoots):
    return build_skill_catalog(discover_sources(roots), global_tool_names=set())


def test_activation_renders_input_persists_and_preserves_order(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "first", "Do {{input}}")
    _write(roots.project, "second", "No placeholder")
    binding = Binding()
    runtime = SkillRuntime(_catalog(roots), tmp_path, ToolRegistry([]), binding=binding)
    runtime.activate("first", "one")
    runtime.activate("second", "two")
    runtime.activate("first", "new")
    assert [item.name for item in runtime.active] == ["first", "second"]
    assert runtime.active[0].rendered_sop == "Do new"
    assert runtime.active[1].rendered_sop.endswith("Task input:\ntwo")
    assert binding.values[-1] == (
        StoredSkillActivation("first", "new"),
        StoredSkillActivation("second", "two"),
    )


def test_prompt_only_contains_shared_active_sops(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "shared", "Shared body")
    _write(roots.project, "private", "Private body", "isolated")
    runtime = SkillRuntime(_catalog(roots), tmp_path, ToolRegistry([]))
    runtime.activate("shared")
    runtime.activate("private")
    additions = runtime.prompt_additions()
    assert "shared: shared description" in additions.available_skills
    assert "Shared body" in additions.active_skills
    assert "Private body" not in additions.active_skills


def test_restore_ignores_missing_skill_and_persists_correction(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "present", "Body {{input}}")
    binding = Binding()
    runtime = SkillRuntime(_catalog(roots), tmp_path, ToolRegistry([]), binding=binding)
    diagnostics = runtime.restore(
        [StoredSkillActivation("missing", "x"), StoredSkillActivation("present", "y")]
    )
    assert [item.name for item in runtime.active] == ["present"]
    assert diagnostics and binding.values[-1] == (StoredSkillActivation("present", "y"),)


def test_refresh_rebinds_fallback_and_rejects_bad_candidate(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.user, "sample", "User {{input}}")
    _write(roots.project, "sample", "Project {{input}}")
    runtime = SkillRuntime(_catalog(roots), tmp_path, ToolRegistry([]))
    runtime.activate("sample", "x")
    (roots.project / "sample.md").unlink()
    sources = discover_sources(roots)
    fingerprint = tuple(sorted((item.fingerprint for item in sources), key=lambda item: (item.root, item.files)))
    result = runtime.refresh(fingerprint, lambda: _catalog(roots))
    assert result.accepted and runtime.active[0].rendered_sop == "User x"

    old = runtime.catalog
    result = runtime.refresh((object(),), lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    assert not result.accepted and runtime.catalog is old
