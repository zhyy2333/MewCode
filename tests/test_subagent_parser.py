from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.permissions import PermissionMode
from mewcode.subagents import (
    MAX_DEFINITION_FILE_BYTES,
    AgentDefinitionError,
    AgentDefinitionLayer,
    AgentDefinitionSource,
    parse_agent_definition,
)


def _source(path: Path) -> AgentDefinitionSource:
    return AgentDefinitionSource(
        AgentDefinitionLayer.PROJECT,
        path.parent,
        path,
        path.stem,
        "project",
    )


def _document(
    *,
    name: str = "reviewer",
    description: str = "Review code",
    tools: str = "[read_file]",
    disallowed_tools: str = "[]",
    model: str = "inherit",
    max_turns: object = 20,
    permission_mode: str = "default",
    body: str = "You are a reviewer.",
    newline: str = "\n",
) -> str:
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"tools: {tools}",
        f"disallowed_tools: {disallowed_tools}",
        f"model: {model}",
        f"max_turns: {max_turns}",
        f"permission_mode: {permission_mode}",
        "---",
        body,
    ]
    return newline.join(lines)


def test_parse_valid_definition_with_lf_crlf_and_bom(tmp_path: Path) -> None:
    for index, (newline, bom) in enumerate((("\n", b""), ("\r\n", b"\xef\xbb\xbf"))):
        path = tmp_path / f"reviewer-{index}.md"
        text = _document(name=path.stem, newline=newline)
        path.write_bytes(bom + text.encode("utf-8"))
        definition = parse_agent_definition(_source(path))
        assert definition.name == path.stem
        assert definition.tools == ("read_file",)
        assert definition.permission_mode is PermissionMode.DEFAULT
        assert definition.system_prompt == "You are a reviewer."


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("name: reviewer", "start with"),
        ("---\nname: reviewer", "not closed"),
        ("---\n- list\n---\nbody", "YAML object"),
        (_document(body="   "), "must not be empty"),
        (_document(name="Bad_Name"), "kebab-case"),
        (_document(description="''"), "non-empty string"),
        (_document(tools="read_file"), "must be a list"),
        (_document(tools="[read_file, read_file]"), "duplicates"),
        (_document(max_turns=True), "integer from 1"),
        (_document(max_turns=0), "integer from 1"),
        (_document(max_turns=101), "integer from 1"),
        (_document(permission_mode="interactive"), "strict, default, or allow"),
        (_document().replace("model: inherit", "extra: value\nmodel: inherit"), "exactly seven"),
        (_document().replace("model: inherit\n", ""), "exactly seven"),
        (_document().replace("name: reviewer", "name: reviewer\nname: reviewer"), "Invalid"),
    ],
)
def test_invalid_definition_shell_and_fields(
    tmp_path: Path,
    payload: str,
    match: str,
) -> None:
    path = tmp_path / "reviewer.md"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(AgentDefinitionError, match=match):
        parse_agent_definition(_source(path))


def test_invalid_utf8_link_diagnostic_and_file_limit(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff")
    with pytest.raises(AgentDefinitionError, match="UTF-8"):
        parse_agent_definition(_source(invalid))

    linked = AgentDefinitionSource(
        AgentDefinitionLayer.USER,
        tmp_path,
        invalid,
        "invalid",
        "user",
        "Symbolic links are denied.",
    )
    with pytest.raises(AgentDefinitionError, match="Symbolic links"):
        parse_agent_definition(linked)

    oversized = tmp_path / "oversized.md"
    oversized.write_bytes(b"x" * (MAX_DEFINITION_FILE_BYTES + 1))
    with pytest.raises(AgentDefinitionError, match="exceeds"):
        parse_agent_definition(_source(oversized))


def test_exact_file_limit_is_read_before_yaml_validation(tmp_path: Path) -> None:
    path = tmp_path / "reviewer.md"
    base = _document(body="x")
    payload = base[:-1] + "x" * (MAX_DEFINITION_FILE_BYTES - len(base.encode("utf-8")) + 1)
    assert len(payload.encode("utf-8")) == MAX_DEFINITION_FILE_BYTES
    path.write_bytes(payload.encode("utf-8"))
    assert parse_agent_definition(_source(path)).system_prompt.startswith("x")


def test_documented_code_reviewer_example_parses_with_read_only_tools() -> None:
    path = Path(__file__).resolve().parents[1] / "examples" / "agents" / "code-reviewer.md"
    source = AgentDefinitionSource(
        AgentDefinitionLayer.PROJECT,
        path.parent,
        path,
        "code-reviewer",
        "example",
    )
    definition = parse_agent_definition(source)
    assert definition.tools == ("read_file", "find_files", "search_code")
    assert definition.disallowed_tools == ()
    assert definition.model == "inherit"
    assert "severity order" in definition.system_prompt
