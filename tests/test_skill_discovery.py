from __future__ import annotations

from pathlib import Path

from mewcode.skills import SkillLayer, SkillRoots, discover_layer, discover_sources


def _entry(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {name}\ntools: []\nmode: shared\n---\nBody",
        encoding="utf-8",
    )


def test_discovers_file_and_directory_entries_in_stable_order(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _entry(root / "zeta.md", "zeta")
    _entry(root / "alpha" / "SKILL.md", "alpha")
    _entry(root / "ignored" / "OTHER.md", "ignored")

    sources = discover_layer(root, SkillLayer.PROJECT)

    assert [source.entry_name for source in sources] == ["alpha", "zeta"]
    assert sources[0].package_dir == (root / "alpha").resolve()
    assert sources[1].package_dir is None


def test_discovers_project_user_builtin_in_priority_order(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    for root in (roots.project, roots.user, roots.builtin):
        _entry(root / "sample.md", "sample")

    sources = discover_sources(roots)

    assert [source.layer for source in sources] == [
        SkillLayer.PROJECT,
        SkillLayer.USER,
        SkillLayer.BUILTIN,
    ]


def test_fingerprint_changes_with_file_metadata(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    path = root / "sample.md"
    _entry(path, "sample")
    before = discover_layer(root, SkillLayer.PROJECT)[0].fingerprint
    path.write_text(path.read_text(encoding="utf-8") + "!", encoding="utf-8")
    after = discover_layer(root, SkillLayer.PROJECT)[0].fingerprint
    assert before != after
