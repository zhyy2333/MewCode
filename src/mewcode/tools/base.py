from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

ToolParameterSchema = dict[str, Any]
DEFAULT_TOOL_CONTENT_LIMIT = 20_000


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool_name: str
    content: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        if self.ok:
            return self.content.splitlines()[0][:120] if self.content else "ok"
        return (self.error or "failed")[:120]


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: ToolParameterSchema

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...


def truncate_text(
    text: str, limit: int = DEFAULT_TOOL_CONTENT_LIMIT
) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n[truncated]", True


def validate_arguments(schema: ToolParameterSchema, arguments: dict[str, Any]) -> str | None:
    if not isinstance(arguments, dict):
        return "Tool arguments must be a JSON object."

    required = schema.get("required", [])
    for field_name in required:
        if field_name not in arguments:
            return f"Missing required argument: {field_name}"

    properties = schema.get("properties", {})
    for field_name, value in arguments.items():
        if field_name not in properties:
            continue
        expected = properties[field_name].get("type")
        if expected and not _matches_json_type(value, expected):
            return f"Argument '{field_name}' must be {expected}."
    return None


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def execute(self, request: ToolCallRequest) -> ToolResult:
        tool = self.get(request.name)
        if tool is None:
            return ToolResult(
                ok=False,
                tool_name=request.name,
                content="",
                error=f"Unknown tool: {request.name}",
                metadata={"tool_call_id": request.id},
            )

        validation_error = validate_arguments(tool.parameters_schema, request.arguments)
        if validation_error is not None:
            return ToolResult(
                ok=False,
                tool_name=tool.name,
                content="",
                error=validation_error,
                metadata={
                    "tool_call_id": request.id,
                    "raw_arguments": request.raw_arguments,
                },
            )

        try:
            return tool.execute(request.arguments)
        except Exception as exc:
            return ToolResult(
                ok=False,
                tool_name=tool.name,
                content="",
                error=f"Tool raised an unexpected error: {exc}",
                metadata={"tool_call_id": request.id},
            )

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters_schema,
            }
            for tool in self.list()
        ]

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
                "strict": False,
            }
            for tool in self.list()
        ]
