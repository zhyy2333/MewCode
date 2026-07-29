from __future__ import annotations

from typing import Any

from mewcode.tools import ToolCallRequest, ToolRegistry, ToolResult, truncate_text
from mewcode.tools import create_builtin_registry
from mewcode.tools.workspace import Workspace


class EchoTool:
    name = "echo"
    description = "Echo text."
    parameters_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, tool_name=self.name, content=arguments["text"])


class RaisingTool:
    name = "raising"
    description = "Raise."
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError("boom")


def test_registry_finds_registered_tool() -> None:
    registry = ToolRegistry([EchoTool()])

    assert registry.get("echo") is not None
    assert registry.get("missing") is None
    assert [tool.name for tool in registry.list()] == ["echo"]


def test_registry_executes_tool() -> None:
    registry = ToolRegistry([EchoTool()])
    result = registry.execute(
        ToolCallRequest(
            id="call_1",
            name="echo",
            arguments={"text": "hello"},
            raw_arguments='{"text":"hello"}',
        )
    )

    assert result.ok is True
    assert result.content == "hello"


def test_registry_returns_unknown_tool_error() -> None:
    registry = ToolRegistry([])
    result = registry.execute(
        ToolCallRequest(id="call_1", name="missing", arguments={}, raw_arguments="{}")
    )

    assert result.ok is False
    assert result.error == "Unknown tool: missing"


def test_registry_validates_required_arguments() -> None:
    registry = ToolRegistry([EchoTool()])
    result = registry.execute(
        ToolCallRequest(id="call_1", name="echo", arguments={}, raw_arguments="{}")
    )

    assert result.ok is False
    assert "Missing required argument" in (result.error or "")


def test_registry_validates_argument_type() -> None:
    registry = ToolRegistry([EchoTool()])
    result = registry.execute(
        ToolCallRequest(id="call_1", name="echo", arguments={"text": 123}, raw_arguments="{}")
    )

    assert result.ok is False
    assert "must be string" in (result.error or "")


def test_registry_wraps_unexpected_tool_error() -> None:
    registry = ToolRegistry([RaisingTool()])
    result = registry.execute(
        ToolCallRequest(id="call_1", name="raising", arguments={}, raw_arguments="{}")
    )

    assert result.ok is False
    assert "unexpected error" in (result.error or "")


def test_anthropic_tool_format() -> None:
    registry = ToolRegistry([EchoTool()])

    assert registry.to_anthropic_tools() == [
        {
            "name": "echo",
            "description": "Echo text.",
            "input_schema": EchoTool.parameters_schema,
        }
    ]


def test_openai_tool_format() -> None:
    registry = ToolRegistry([EchoTool()])

    assert registry.to_openai_tools() == [
        {
            "type": "function",
            "name": "echo",
            "description": "Echo text.",
            "parameters": EchoTool.parameters_schema,
        }
    ]


def test_truncate_text_marks_truncated_content() -> None:
    text, truncated = truncate_text("abcdef", limit=3)

    assert text == "abc\n[truncated]"
    assert truncated is True


def test_truncate_text_keeps_short_content() -> None:
    text, truncated = truncate_text("abc", limit=3)

    assert text == "abc"
    assert truncated is False


def test_builtin_registry_contains_six_core_tools(tmp_path) -> None:
    registry = create_builtin_registry(Workspace(tmp_path))

    assert [tool.name for tool in registry.list()] == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "find_files",
        "search_code",
    ]
    for name in ["read_file", "write_file", "edit_file", "run_command", "find_files", "search_code"]:
        assert registry.get(name) is not None


def test_builtin_registry_exports_all_tools_for_providers(tmp_path) -> None:
    registry = create_builtin_registry(Workspace(tmp_path))

    assert [tool["name"] for tool in registry.to_anthropic_tools()] == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "find_files",
        "search_code",
    ]
    assert [tool["name"] for tool in registry.to_openai_tools()] == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "find_files",
        "search_code",
    ]
