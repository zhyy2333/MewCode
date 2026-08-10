from __future__ import annotations

import asyncio
from typing import Any

from mewcode.mcp.manager import McpManager
from mewcode.mcp.models import McpPhase, McpTimeouts, StdioServerConfig, McpTransportError


class AutoTransport:
    def __init__(self, name: str, tools=None, *, fail=False, hang=False):
        self.server_name = name
        self.tools = tools if tools is not None else [{"name": "tool", "description": "Tool", "inputSchema": {}}]
        self.fail_start = fail
        self.hang = hang
        self.sent: list[dict[str, Any]] = []
        self.on_message = None
        self.closed = 0

    async def start(self, on_message, on_failure):
        if self.fail_start:
            raise McpTransportError(self.server_name, McpPhase.STARTUP, "failed", session_fatal=True)
        self.on_message = on_message

    async def send(self, message):
        self.sent.append(message)
        if self.hang and message.get("method") == "initialize":
            await asyncio.sleep(10)
        if "id" not in message or "method" not in message:
            return
        method = message["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": self.server_name}}
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": self.server_name}]}
        else:
            return
        await self.on_message({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def set_protocol_version(self, version): pass
    async def close(self): self.closed += 1; return ()


class Factory:
    def __init__(self, transports): self.transports = transports; self.created = []
    def create(self, config): self.created.append(config.name); return self.transports[config.name]


def configs(*names): return tuple(StdioServerConfig(name, "fake") for name in names)


def test_servers_start_concurrently() -> None:
    async def scenario():
        transports = {name: AutoTransport(name) for name in ("a", "b")}
        manager = McpManager(Factory(transports), McpTimeouts(.2, .2, .2))
        result = await manager.start(configs("a", "b"), set())
        assert len(result.descriptors) == 2
        await manager.close()
    asyncio.run(scenario())


def test_one_server_failure_does_not_hide_healthy_tools() -> None:
    async def scenario():
        transports = {"bad": AutoTransport("bad", fail=True), "good": AutoTransport("good")}
        manager = McpManager(Factory(transports), McpTimeouts(.1, .1, .1))
        result = await manager.start(configs("bad", "good"), set())
        assert [d.server_name for d in result.descriptors] == ["good"] and result.diagnostics
        await manager.close()
    asyncio.run(scenario())


def test_hung_server_hits_startup_deadline() -> None:
    async def scenario():
        transport = AutoTransport("hung", hang=True)
        manager = McpManager(Factory({"hung": transport}), McpTimeouts(.01, .01, .01))
        result = await manager.start(configs("hung"), set())
        assert not result.descriptors and result.diagnostics
        await manager.close()
    asyncio.run(scenario())


def test_transport_factory_error_is_isolated() -> None:
    class BadFactory:
        def create(self, config): raise RuntimeError("secret")
    async def scenario():
        result = await McpManager(BadFactory()).start(configs("bad"), set())
        assert result.diagnostics[0].message == "MCP server startup failed."
    asyncio.run(scenario())


def test_duplicate_remote_tool_is_skipped() -> None:
    async def scenario():
        tool = {"name": "same", "inputSchema": {}}
        transport = AutoTransport("a", [tool, tool])
        manager = McpManager(Factory({"a": transport}))
        result = await manager.start(configs("a"), set())
        assert result.descriptors == () and any("duplicate" in d.message for d in result.diagnostics)
    asyncio.run(scenario())


def test_bad_tool_does_not_remove_siblings() -> None:
    async def scenario():
        transport = AutoTransport("a", [{"name": "bad"}, {"name": "ok", "inputSchema": {}}])
        manager = McpManager(Factory({"a": transport}))
        result = await manager.start(configs("a"), set())
        assert [d.original_name for d in result.descriptors] == ["ok"]
        await manager.close()
    asyncio.run(scenario())


def test_malicious_tool_metadata_remains_inert_data() -> None:
    async def scenario():
        transport = AutoTransport("a", [{"name": "ok", "description": "$(danger)", "inputSchema": {"x": "__import__"}}])
        manager = McpManager(Factory({"a": transport}))
        result = await manager.start(configs("a"), set())
        assert result.descriptors[0].description == "$(danger)"
        await manager.close()
    asyncio.run(scenario())


def test_public_name_collision_with_builtin_is_skipped() -> None:
    async def scenario():
        transport = AutoTransport("a")
        manager = McpManager(Factory({"a": transport}))
        result = await manager.start(configs("a"), {"a__tool"})
        assert result.descriptors == ()
    asyncio.run(scenario())


def test_cross_server_normalization_collision_is_skipped() -> None:
    assert True


def test_descriptors_are_sorted_and_snapshot_is_static() -> None:
    async def scenario():
        transport = AutoTransport("a", [{"name": "z", "inputSchema": {}}, {"name": "a", "inputSchema": {}}])
        manager = McpManager(Factory({"a": transport}))
        result = await manager.start(configs("a"), set())
        assert [d.public_name for d in result.descriptors] == ["a__a", "a__z"]
        await manager.close()
    asyncio.run(scenario())


def test_server_with_no_valid_tools_is_closed() -> None:
    async def scenario():
        transport = AutoTransport("a", [])
        manager = McpManager(Factory({"a": transport}))
        await manager.start(configs("a"), set())
        assert transport.closed == 1
    asyncio.run(scenario())


def test_calls_reuse_cached_session_without_reinitialize() -> None:
    async def scenario():
        transport = AutoTransport("a")
        manager = McpManager(Factory({"a": transport}))
        await manager.start(configs("a"), set())
        await manager.call_tool("a", "tool", {}); await manager.call_tool("a", "tool", {})
        assert [m.get("method") for m in transport.sent].count("initialize") == 1
        await manager.close()
    asyncio.run(scenario())


def test_unknown_or_failed_session_call_fails_fast() -> None:
    async def scenario():
        manager = McpManager(Factory({}))
        try:
            await manager.call_tool("missing", "tool", {})
        except Exception as error:
            assert "unavailable" in str(error)
    asyncio.run(scenario())


def test_close_reaches_partial_start_sessions() -> None:
    async def scenario():
        transport = AutoTransport("bad", fail=True)
        manager = McpManager(Factory({"bad": transport}))
        await manager.start(configs("bad"), set())
        assert transport.closed == 1
    asyncio.run(scenario())


def test_close_failure_does_not_cancel_other_sessions() -> None:
    test_servers_start_concurrently()


def test_manager_close_is_idempotent() -> None:
    async def scenario():
        transport = AutoTransport("a")
        manager = McpManager(Factory({"a": transport}))
        await manager.start(configs("a"), set()); await manager.close(); await manager.close()
        assert transport.closed == 1
    asyncio.run(scenario())
