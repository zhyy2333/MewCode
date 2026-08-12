from __future__ import annotations

import json
from pathlib import Path

import pytest

from mewcode.skills import SkillDefinitionError, SkillLayer, SkillMode, discover_layer, parse_skill


def write_skill(root: Path, name: str, frontmatter: str, body: str = "Do {{input}}") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


def test_parses_strict_shared_skill_without_loading_body(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(
        root,
        "format-code",
        "name: format-code\ndescription: Format changed code\ntools: [read_file]\nmode: shared",
    )

    definition = parse_skill(discover_layer(root, SkillLayer.PROJECT)[0])

    assert definition.name == "format-code"
    assert definition.mode is SkillMode.SHARED
    assert definition.history is None
    assert definition.body.byte_size == len("Do {{input}}".encode())


@pytest.mark.parametrize(
    "extra",
    ["unknown: true", "history: 1", "model: other"],
)
def test_shared_skill_rejects_unknown_or_conditional_fields(tmp_path: Path, extra: str) -> None:
    root = tmp_path / "skills"
    write_skill(
        root,
        "sample",
        f"name: sample\ndescription: Sample\ntools: []\nmode: shared\n{extra}",
    )

    with pytest.raises(SkillDefinitionError):
        parse_skill(discover_layer(root, SkillLayer.PROJECT)[0])


def test_isolated_skill_requires_nonnegative_history(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "sample", "name: sample\ndescription: Sample\ntools: []\nmode: isolated")
    with pytest.raises(SkillDefinitionError, match="history"):
        parse_skill(discover_layer(root, SkillLayer.PROJECT)[0])


def test_directory_package_parses_tool_declaration(tmp_path: Path) -> None:
    package = tmp_path / "skills" / "audit"
    (package / "tools").mkdir(parents=True)
    (package / "scripts").mkdir()
    (package / "SKILL.md").write_text(
        "---\nname: audit\ndescription: Audit files\ntools: [audit__check]\nmode: isolated\nhistory: 0\n---\nAudit",
        encoding="utf-8",
    )
    (package / "scripts" / "check.py").write_text("print('{}')", encoding="utf-8")
    (package / "tools" / "check.json").write_text(
        json.dumps(
            {
                "name": "check",
                "description": "Check files",
                "parameters": {"type": "object", "properties": {}},
                "command": ["python", "scripts/check.py"],
                "safety": "read_only",
            }
        ),
        encoding="utf-8",
    )

    definition = parse_skill(discover_layer(package.parent, SkillLayer.PROJECT)[0])

    assert definition.package_tools[0].public_name == "audit__check"
    assert definition.package_tools[0].timeout_seconds == 60


def test_tool_command_cannot_escape_package(tmp_path: Path) -> None:
    package = tmp_path / "skills" / "audit"
    (package / "tools").mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: audit\ndescription: Audit\ntools: [audit__check]\nmode: shared\n---\nAudit",
        encoding="utf-8",
    )
    (tmp_path / "outside.py").write_text("pass", encoding="utf-8")
    (package / "tools" / "check.json").write_text(
        json.dumps(
            {
                "name": "check",
                "description": "Check",
                "parameters": {"type": "object"},
                "command": ["python", "../../outside.py"],
                "safety": "read_only",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillDefinitionError, match="escapes"):
        parse_skill(discover_layer(package.parent, SkillLayer.PROJECT)[0])
