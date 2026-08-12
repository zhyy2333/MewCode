from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.skills import (
    SkillDefinitionError,
    SkillLayer,
    SkillMaterializer,
    discover_layer,
    parse_skill,
)


def _definition(tmp_path: Path):
    package = tmp_path / "skills" / "sample"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: sample\ndescription: Sample\ntools: []\nmode: shared\n---\nBody",
        encoding="utf-8",
    )
    (package / "data.txt").write_text("old", encoding="utf-8")
    return parse_skill(discover_layer(package.parent, SkillLayer.PROJECT)[0]), package


def test_materializes_immutable_package_copy_and_cleans_it(tmp_path: Path) -> None:
    definition, source = _definition(tmp_path)
    materializer = SkillMaterializer(tmp_path / "runtime")
    materialized = materializer.materialize(definition)
    assert materialized is not None
    source.joinpath("data.txt").write_text("new", encoding="utf-8")
    assert materialized.root.joinpath("data.txt").read_text(encoding="utf-8") == "old"
    materializer.release(materialized)
    assert not materialized.root.exists()


def test_materialization_rejects_source_changed_before_activation(tmp_path: Path) -> None:
    definition, source = _definition(tmp_path)
    source.joinpath("data.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(SkillDefinitionError, match="changed before"):
        SkillMaterializer(tmp_path / "runtime").materialize(definition)
