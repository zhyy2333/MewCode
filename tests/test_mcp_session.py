from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mewcode.mcp.models import McpProtocolError, McpSessionState, McpTimeouts
from mewcode.mcp.session import McpClientSession


class ScriptTransport:
    server_name = "server"

    def __init__(self, *, version="2025-11-25", tools_capability=True, pages=None, call_result=None):
        self.version = version
        self.tools_capability = tools_capability
        self.pages = pages or [{"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]}]
        self.call_result = call_result or {"content": [{"type": "text", "text": "ok"}]}
        self.sent: list[dict[str, Any]] = []
        self.on_message = None
        self.on_failure = None
        self.protocol_version = None
        self.closed = 0

    async def start(self, on_message, on_failure):
        self.on_message, self.on_failure = on_message, on_failure

    async def send(self, message):
        self.sent.append(message)
        if "id" not in message or "method" not in message:
            return
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": self.version,
                "capabilities": {"tools": {}} if self.tools_capability else {},
                "serverInfo": {"name": "fake", "version": "1"},
            }
        elif method == "tools/list":
            cursor = message.get("params", {}).get("cursor")
            index = 0 if cursor is None else int(cursor)
            result = self.pages[index]
        elif method == "tools/call":
            result = self.call_result
        else:
            return
        await self.on_message({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def set_protocol_version(self, version):
        self.protocol_version = version

    async def close(self):
        self.closed += 1
        return ()


def run_start(transport: ScriptTransport):
    async def scenario():
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        tools = await session.start()
        return session, tools
    return asyncio.run(scenario())


def test_initialize_payload_and_initialized_order_are_exact() -> None:
    session, _ = run_start(ScriptTransport())
    methods = [m.get("method") for m in session._transport.sent]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert session._transport.sent[0]["params"]["protocolVersion"] == "2025-11-25"
    assert session._transport.protocol_version == "2025-11-25"


def test_rejects_wrong_protocol_version() -> None:
    with pytest.raises(McpProtocolError, match="unsupported"):
        run_start(ScriptTransport(version="2026-07-28"))


def test_rejects_missing_tools_capability() -> None:
    with pytest.raises(McpProtocolError, match="tools capability"):
        run_start(ScriptTransport(tools_capability=False))


def test_rejects_malformed_initialize_result() -> None:
    class Bad(ScriptTransport):
        async def send(self, message):
            if message.get("method") == "initialize":
                await self.on_message({"jsonrpc": "2.0", "id": message["id"], "result": []})
            else:
                await super().send(message)
    with pytest.raises(McpProtocolError):
        run_start(Bad())


def test_lists_tools_after_initialized_then_becomes_ready() -> None:
    session, tools = run_start(ScriptTransport())
    assert session.state == McpSessionState.READY and tools[0]["name"] == "echo"


def test_call_before_ready_fails_fast() -> None:
    async def scenario():
        transport = ScriptTransport()
        session = McpClientSession("server", transport)
        with pytest.raises(Exception, match="unavailable"):
            await session.call_tool("echo", {})
    asyncio.run(scenario())


def test_collects_all_tool_pages_with_cursor() -> None:
    pages = [
        {"tools": [{"name": "a", "inputSchema": {}}], "nextCursor": "1"},
        {"tools": [{"name": "b", "inputSchema": {}}]},
    ]
    session, tools = run_start(ScriptTransport(pages=pages))
    assert [tool["name"] for tool in tools] == ["a", "b"]
    assert session._transport.sent[-1]["params"] == {"cursor": "1"}


def test_malformed_tools_page_fails_session() -> None:
    with pytest.raises(McpProtocolError):
        run_start(ScriptTransport(pages=[{"tools": "bad"}]))


def test_repeated_cursor_fails_without_looping() -> None:
    pages = [
        {"tools": [], "nextCursor": "1"},
        {"tools": [], "nextCursor": "1"},
    ]
    with pytest.raises(McpProtocolError, match="cursor"):
        run_start(ScriptTransport(pages=pages))


def test_invalid_tool_definition_is_skipped_without_losing_valid_tools() -> None:
    pages = [{"tools": [{"name": "bad"}, {"name": "ok", "inputSchema": {}}]}]
    session, tools = run_start(ScriptTransport(pages=pages))
    assert [tool["name"] for tool in tools] == ["ok"]
    assert session.diagnostics


def test_tools_call_uses_original_name_and_unchanged_arguments() -> None:
    async def scenario():
        transport = ScriptTransport()
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        await session.start()
        arguments = {"nested": {"x": 1}}
        await session.call_tool("remote.echo", arguments)
        sent = transport.sent[-1]["params"]
        assert sent == {"name": "remote.echo", "arguments": arguments}
    asyncio.run(scenario())


def test_parses_call_result_fields() -> None:
    async def scenario():
        transport = ScriptTransport(call_result={"content": [], "structuredContent": {"b": 2}, "isError": True})
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        await session.start()
        result = await session.call_tool("echo", {})
        assert result.is_error and result.structured_content == {"b": 2}
    asyncio.run(scenario())


def test_call_error_and_timeout_leave_session_ready() -> None:
    async def scenario():
        transport = ScriptTransport(call_result={"content": [], "isError": True})
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        await session.start()
        await session.call_tool("echo", {})
        assert session.state == McpSessionState.READY
    asyncio.run(scenario())


def test_malformed_call_result_returns_controlled_error() -> None:
    async def scenario():
        transport = ScriptTransport(call_result={"content": "bad"})
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        await session.start()
        with pytest.raises(McpProtocolError):
            await session.call_tool("echo", {})
        assert session.state == McpSessionState.READY
    asyncio.run(scenario())


def test_fatal_transport_failure_disables_session_without_reconnect() -> None:
    async def scenario():
        transport = ScriptTransport()
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        await session.start()
        await transport.on_failure(McpProtocolError("server", "call", "gone", session_fatal=True))
        with pytest.raises(Exception, match="unavailable"):
            await session.call_tool("echo", {})
        assert session.state == McpSessionState.FAILED
    asyncio.run(scenario())


def test_session_close_is_idempotent() -> None:
    async def scenario():
        transport = ScriptTransport()
        session = McpClientSession("server", transport, McpTimeouts(1, 1, 1))
        await session.start()
        await session.close(); await session.close()
        assert transport.closed == 1 and session.state == McpSessionState.CLOSED
    asyncio.run(scenario())
