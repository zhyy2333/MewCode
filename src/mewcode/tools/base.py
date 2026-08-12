from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
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


def serialize_tool_result(result: ToolResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "content": result.content,
            "error": result.error,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


class ToolSafety(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"


class PermissionTargetKind(StrEnum):
    COMMAND = "command"
    PATH = "path"
    PATH_GLOB = "path_glob"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolPermissionSpec:
    argument: str | None
    kind: PermissionTargetKind
    default: str | None = None


@dataclass(frozen=True)
class ToolExecution:
    index: int
    request: ToolCallRequest
    result: ToolResult


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: ToolParameterSchema
    safety: ToolSafety
    permission_spec: ToolPermissionSpec

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...


@dataclass(frozen=True)
class ValidatedToolCall:
    request: ToolCallRequest
    tool: Tool


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
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def merge(self, *others: ToolRegistry) -> ToolRegistry:
        return ToolRegistry(
            tool for registry in (self, *others) for tool in registry.list()
        )

    def select_names(self, names: Iterable[str]) -> ToolRegistry:
        selected = set(names)
        return ToolRegistry(tool for tool in self.list() if tool.name in selected)

    def without(self, names: Iterable[str]) -> ToolRegistry:
        excluded = set(names)
        return ToolRegistry(tool for tool in self.list() if tool.name not in excluded)

    def select_safety(self, safety: set[ToolSafety]) -> ToolRegistry:
        return ToolRegistry(tool for tool in self.list() if tool.safety in safety)

    def select(self, safety: set[ToolSafety]) -> ToolRegistry:
        return self.select_safety(safety)

    def validate_call(self, request: ToolCallRequest) -> ValidatedToolCall | ToolResult:
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

        return ValidatedToolCall(request=request, tool=tool)

    async def execute_validated(self, call: ValidatedToolCall) -> ToolResult:
        try:
            return await call.tool.execute(call.request.arguments)
        except Exception as exc:
            return ToolResult(
                ok=False,
                tool_name=call.tool.name,
                content="",
                error=f"Tool raised an unexpected error: {exc}",
                metadata={"tool_call_id": call.request.id},
            )

    async def execute(self, request: ToolCallRequest) -> ToolResult:
        validated = self.validate_call(request)
        if isinstance(validated, ToolResult):
            return validated
        return await self.execute_validated(validated)
