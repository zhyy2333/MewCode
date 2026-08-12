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


def test_refresh_unchanged_skips_rebuild_and_disappearance_deactivates_once(
    tmp_path: Path,
) -> None:
    roots = SkillRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "sample", "Body {{input}}")
    binding = Binding()
    runtime = SkillRuntime(_catalog(roots), tmp_path, ToolRegistry([]), binding=binding)
    runtime.activate("sample", "focus")

    unchanged = runtime.refresh(
        runtime.catalog.fingerprint,
        lambda: (_ for _ in ()).throw(AssertionError("catalog must not be rebuilt")),
    )
    assert not unchanged.changed and unchanged.accepted

    (roots.project / "sample.md").unlink()
    candidate = _catalog(roots)
    removed = runtime.refresh(candidate.fingerprint, lambda: candidate)
    assert removed.changed and removed.accepted
    assert runtime.active == ()
    assert binding.values[-1] == ()
    assert sum("disappeared" in item.message for item in removed.diagnostics) == 1

    again = runtime.refresh(candidate.fingerprint, lambda: candidate)
    assert not again.changed and again.diagnostics == ()


def test_activation_rejects_same_length_body_change_before_refresh(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "p", tmp_path / "u", tmp_path / "b")
    _write(roots.project, "sample", "Body one")
    runtime = SkillRuntime(_catalog(roots), tmp_path, ToolRegistry([]))
    path = roots.project / "sample.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("Body one", "Body two"), encoding="utf-8")
    import pytest
    from mewcode.skills import SkillDefinitionError

    with pytest.raises(SkillDefinitionError, match="changed before"):
        runtime.activate("sample")
