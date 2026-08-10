from __future__ import annotations

import json
from typing import Any, Protocol

from mewcode.tools import (
    DEFAULT_TOOL_CONTENT_LIMIT,
    PermissionTargetKind,
    ToolPermissionSpec,
    ToolResult,
    ToolSafety,
    truncate_text,
)

from .models import McpCallResult, McpError, McpPhase, McpToolDescriptor


class McpToolRuntime(Protocol):
    async def call_tool(
        self, server_name: str, original_name: str, arguments: dict[str, Any]
    ) -> McpCallResult: ...


def adapt_mcp_result(
    public_name: str,
    result: McpCallResult,
    content_limit: int = DEFAULT_TOOL_CONTENT_LIMIT,
) -> ToolResult:
    parts = [_adapt_block(block) for block in result.content]
    parts = [part for part in parts if part]
    if result.structured_content is not None:
        parts.append(
            json.dumps(
                result.structured_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    content, truncated = truncate_text("\n\n".join(parts), content_limit)
    return ToolResult(
        ok=not result.is_error,
        tool_name=public_name,
        content=content,
        error="MCP tool reported an execution error." if result.is_error else None,
        metadata={
            "mcp_is_error": result.is_error,
            "content_types": tuple(block.get("type", "unknown") for block in result.content),
            "truncated": truncated,
        },
    )


def mcp_failure_result(
    public_name: str, server_name: str, error: McpError
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=public_name,
        content="",
        error=f"MCP server '{server_name}' tool '{public_name}' failed: {error.safe_message}",
        metadata={"server_name": server_name, "mcp_is_error": True},
    )


def _adapt_block(block: dict[str, Any]) -> str:
    kind = block.get("type", "unknown")
    if kind == "text":
        return block.get("text", "") if isinstance(block.get("text"), str) else ""
    if kind == "resource_link":
        return _describe_resource(block)
    if kind == "resource":
        resource = block.get("resource")
        if not isinstance(resource, dict):
            return "resource: content omitted"
        description = _describe_resource(resource)
        text = resource.get("text")
        if isinstance(text, str):
            return f"{description}\n{text}"
        return f"{description}\ncontent omitted"
    if kind in {"image", "audio"}:
        mime = block.get("mimeType", "unknown")
        return f"{kind} ({mime}): content omitted"
    return f"{kind}: content omitted"


def _describe_resource(block: dict[str, Any]) -> str:
    fields = ["resource"]
    if isinstance(block.get("name"), str):
        fields.append(f"name={block['name']}")
    if isinstance(block.get("uri"), str):
        fields.append(f"uri={block['uri']}")
    if isinstance(block.get("mimeType"), str):
        fields.append(f"mime={block['mimeType']}")
    return " ".join(fields)


class McpTool:
    safety = ToolSafety.SIDE_EFFECT
    permission_spec = ToolPermissionSpec(
        argument=None,
        kind=PermissionTargetKind.TOOL,
        default="invoke",
    )

    def __init__(self, descriptor: McpToolDescriptor, runtime: McpToolRuntime) -> None:
        self._descriptor = descriptor
        self._runtime = runtime
        self.name = descriptor.public_name
        self.description = descriptor.description
        self.parameters_schema = descriptor.input_schema

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = await self._runtime.call_tool(
                self._descriptor.server_name,
                self._descriptor.original_name,
                arguments,
            )
            adapted = adapt_mcp_result(self.name, result)
            metadata = dict(adapted.metadata)
            metadata.update(
                {
                    "server_name": self._descriptor.server_name,
                    "original_tool_name": self._descriptor.original_name,
                }
            )
            return ToolResult(
                adapted.ok,
                adapted.tool_name,
                adapted.content,
                adapted.error,
                metadata,
            )
        except McpError as exc:
            return mcp_failure_result(self.name, self._descriptor.server_name, exc)
        except Exception:
            return mcp_failure_result(
                self.name,
                self._descriptor.server_name,
                McpError(
                    self._descriptor.server_name,
                    McpPhase.CALL,
                    "MCP tool failed unexpectedly.",
                ),
            )
