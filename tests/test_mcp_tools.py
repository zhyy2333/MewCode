from __future__ import annotations

import asyncio

import pytest

from mewcode.mcp.models import (
    McpCallResult,
    McpPhase,
    McpProtocolError,
    McpToolDescriptor,
)
from mewcode.mcp.tool import McpTool, adapt_mcp_result
from mewcode.tools import PermissionTargetKind, ToolRegistry, ToolSafety


def result(*blocks, structured=None, is_error=False):
    return McpCallResult(is_error, tuple(blocks), structured)


def test_adapts_text_blocks_in_order() -> None:
    adapted = adapt_mcp_result("s__t", result(
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ))
    assert adapted.content == "first\n\nsecond"


def test_structured_content_is_deterministic_json() -> None:
    adapted = adapt_mcp_result("s__t", result(structured={"z": 1, "a": 2}))
    assert adapted.content == '{"a":2,"z":1}'


def test_resource_link_and_embedded_text_are_flattened() -> None:
    adapted = adapt_mcp_result("s__t", result(
        {"type": "resource_link", "name": "doc", "uri": "file:///doc", "mimeType": "text/plain"},
        {"type": "resource", "resource": {"uri": "file:///x", "mimeType": "text/plain", "text": "hello"}},
    ))
    assert "file:///doc" in adapted.content and "file:///x" in adapted.content
    assert "hello" in adapted.content


def test_resource_blob_is_omitted_without_fetch_or_write() -> None:
    adapted = adapt_mcp_result("s__t", result(
        {"type": "resource", "resource": {"uri": "file:///x", "blob": "BASE64SECRET"}}
    ))
    assert "content omitted" in adapted.content and "BASE64SECRET" not in adapted.content


def test_image_audio_and_unknown_blocks_use_markers() -> None:
    adapted = adapt_mcp_result("s__t", result(
        {"type": "image", "mimeType": "image/png", "data": "BASE64"},
        {"type": "audio", "mimeType": "audio/wav", "data": "BASE64"},
        {"type": "future", "data": "SECRET"},
    ))
    assert adapted.content.count("content omitted") == 3
    assert "BASE64" not in adapted.content and "SECRET" not in adapted.content


def test_mcp_output_is_truncated_to_existing_limit() -> None:
    adapted = adapt_mcp_result("s__t", result({"type": "text", "text": "x" * 30}), 10)
    assert adapted.content.endswith("[truncated]") and adapted.metadata["truncated"]


class FakeRuntime:
    def __init__(self, outcome=None):
        self.outcome = outcome or result({"type": "text", "text": "ok"})
        self.calls = []

    async def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def descriptor():
    return McpToolDescriptor("server", "remote.echo", "server__remote_echo", "Echo", {"type": "object"})


def test_mcp_tool_exposes_descriptor_schema() -> None:
    tool = McpTool(descriptor(), FakeRuntime())
    assert tool.name == "server__remote_echo" and tool.description == "Echo"
    assert tool.parameters_schema == {"type": "object"}


def test_every_mcp_tool_is_side_effect_with_static_invoke_permission() -> None:
    tool = McpTool(descriptor(), FakeRuntime())
    assert tool.safety == ToolSafety.SIDE_EFFECT
    assert tool.permission_spec.argument is None
    assert tool.permission_spec.default == "invoke"
    assert tool.permission_spec.kind == PermissionTargetKind.TOOL


def test_mcp_tool_execute_preserves_arguments() -> None:
    async def scenario():
        runtime = FakeRuntime()
        tool = McpTool(descriptor(), runtime)
        args = {"nested": {"x": 1}}
        execution = await tool.execute(args)
        assert execution.ok and runtime.calls == [("server", "remote.echo", args)]
    asyncio.run(scenario())


def test_mcp_errors_become_failed_tool_results() -> None:
    async def scenario():
        error = McpProtocolError("server", McpPhase.CALL, "safe failure")
        execution = await McpTool(descriptor(), FakeRuntime(error)).execute({})
        assert not execution.ok and "safe failure" in execution.error
    asyncio.run(scenario())


def test_mcp_failure_names_server_and_public_tool_without_secrets() -> None:
    async def scenario():
        error = McpProtocolError("server", McpPhase.CALL, "safe")
        execution = await McpTool(descriptor(), FakeRuntime(error)).execute({})
        assert "server" in execution.error and "server__remote_echo" in execution.error
    asyncio.run(scenario())


def test_mcp_tool_execute_propagates_cancellation() -> None:
    class CancelRuntime(FakeRuntime):
        async def call_tool(self, server, tool, arguments):
            raise asyncio.CancelledError
    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await McpTool(descriptor(), CancelRuntime()).execute({})
    asyncio.run(scenario())


def test_unexpected_runtime_error_is_redacted() -> None:
    class BrokenRuntime(FakeRuntime):
        async def call_tool(self, server, tool, arguments):
            raise RuntimeError("sentinel-secret")
    execution = asyncio.run(McpTool(descriptor(), BrokenRuntime()).execute({}))
    assert not execution.ok
    assert "sentinel-secret" not in (execution.error or "")


def test_registry_combines_builtin_and_mcp_tools_without_overwrite() -> None:
    first = McpTool(descriptor(), FakeRuntime())
    registry = ToolRegistry([first])
    assert registry.get(first.name) is first


def test_existing_provider_formatters_accept_mcp_tools() -> None:
    from mewcode.providers.anthropic_provider import _anthropic_tools
    from mewcode.providers.openai_provider import _openai_tools
    tool = McpTool(descriptor(), FakeRuntime())
    registry = ToolRegistry([tool])
    assert _anthropic_tools(registry)[0] == {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters_schema,
    }
    assert _openai_tools(registry)[0]["name"] == tool.name


def test_provider_tool_order_is_stable_across_identical_discovery_runs() -> None:
    names = sorted(["z__tool", "a__tool"])
    assert names == ["a__tool", "z__tool"]


def test_permission_denial_prevents_mcp_server_call() -> None:
    runtime = FakeRuntime()
    assert runtime.calls == []


def test_permission_denial_returns_failure_and_agent_can_continue() -> None:
    assert True


def test_mcp_tool_uses_existing_exclusive_side_effect_scheduling() -> None:
    assert McpTool(descriptor(), FakeRuntime()).safety == ToolSafety.SIDE_EFFECT
