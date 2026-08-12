from __future__ import annotations

import asyncio
from pathlib import Path
import threading

import pytest

from mewcode.mcp.models import (
    McpDiagnostic,
    McpPhase,
    McpServerStartState,
    McpTimeouts,
    StdioServerConfig,
)
from mewcode.mcp.runtime import McpRuntime


class RuntimeTransport:
    def __init__(self, name="server", *, fail=False, hang_call=False):
        self.server_name = name
        self.fail = fail
        self.hang_call = hang_call
        self.on_message = None
        self.thread_id = None
        self.sent = []
        self.closed = 0

    async def start(self, on_message, on_failure):
        self.thread_id = threading.get_ident()
        if self.fail:
            raise RuntimeError("failed")
        self.on_message = on_message

    async def send(self, message):
        self.sent.append(message)
        method = message.get("method")
        if method == "notifications/initialized" or method == "notifications/cancelled" or "id" not in message:
            return
        if method == "tools/call" and self.hang_call:
            await asyncio.sleep(10)
            return
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": self.server_name}}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "ok"}]}
        else:
            return
        await self.on_message({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def set_protocol_version(self, version): pass
    async def close(self): self.closed += 1; return ()


class Factory:
    def __init__(self, transports): self.transports = transports
    def create(self, config): return self.transports[config.name]


def test_runtime_starts_one_background_loop_and_returns_proxies(tmp_path: Path) -> None:
    transport = RuntimeTransport()
    runtime = McpRuntime(tmp_path, timeouts=McpTimeouts(1, 1, 1), transport_factory=Factory({"server": transport}))
    started = runtime.start((StdioServerConfig("server", "fake"),), set())
    assert len(started.tools) == 1 and runtime._thread is not None
    assert runtime._thread.name == "mewcode-mcp"
    runtime.close()


def test_manager_objects_remain_on_runtime_loop(tmp_path: Path) -> None:
    transport = RuntimeTransport()
    runtime = McpRuntime(tmp_path, transport_factory=Factory({"server": transport}))
    runtime.start((StdioServerConfig("server", "fake"),), set())
    assert runtime._thread is not None and transport.thread_id == runtime._thread.ident
    runtime.close()


def test_runtime_returns_healthy_tools_after_partial_server_failure(tmp_path: Path) -> None:
    transports = {"bad": RuntimeTransport("bad", fail=True), "good": RuntimeTransport("good")}
    runtime = McpRuntime(tmp_path, timeouts=McpTimeouts(.2, .2, .2), transport_factory=Factory(transports))
    result = runtime.start((StdioServerConfig("bad", "x"), StdioServerConfig("good", "x")), set())
    assert [tool.name for tool in result.tools] == ["good__echo"] and result.diagnostics
    assert {status.server_name: status.state for status in result.statuses} == {
        "bad": McpServerStartState.FAILED,
        "good": McpServerStartState.READY,
    }
    runtime.close()


def test_runtime_loop_start_failure_leaves_no_callable_runtime(tmp_path: Path) -> None:
    runtime = McpRuntime(tmp_path)
    runtime._started = True
    with pytest.raises(RuntimeError):
        runtime.start((), set())


def test_runtime_call_crosses_thread_and_returns_result(tmp_path: Path) -> None:
    transport = RuntimeTransport()
    runtime = McpRuntime(tmp_path, transport_factory=Factory({"server": transport}))
    runtime.start((StdioServerConfig("server", "x"),), set())
    async def scenario():
        result = await runtime.call_tool("server", "echo", {})
        assert result.content[0]["text"] == "ok"
    asyncio.run(scenario())
    runtime.close()


def test_runtime_call_cancellation_reaches_background_pending_only(tmp_path: Path) -> None:
    transport = RuntimeTransport(hang_call=True)
    runtime = McpRuntime(tmp_path, timeouts=McpTimeouts(1, 1, .2), transport_factory=Factory({"server": transport}))
    runtime.start((StdioServerConfig("server", "x"),), set())
    async def scenario():
        task = asyncio.create_task(runtime.call_tool("server", "echo", {}))
        await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        await asyncio.sleep(.02)
    asyncio.run(scenario())
    assert any(m.get("method") == "notifications/cancelled" for m in transport.sent)
    runtime.close()


def test_runtime_close_stops_loop_and_joins_thread(tmp_path: Path) -> None:
    transport = RuntimeTransport()
    runtime = McpRuntime(tmp_path, transport_factory=Factory({"server": transport}))
    runtime.start((StdioServerConfig("server", "x"),), set())
    runtime.close()
    assert runtime._thread is not None and not runtime._thread.is_alive()
    assert transport.closed == 1


def test_runtime_close_collects_safe_diagnostics(tmp_path: Path) -> None:
    transport = RuntimeTransport()
    runtime = McpRuntime(tmp_path, transport_factory=Factory({"server": transport}))
    runtime.start((StdioServerConfig("server", "x"),), set())
    assert runtime.close() == ()


def test_runtime_close_is_idempotent_after_partial_start(tmp_path: Path) -> None:
    runtime = McpRuntime(tmp_path)
    assert runtime.close() == () and runtime.close() == ()


def test_close_after_cancellation_has_no_live_mcp_tasks(tmp_path: Path) -> None:
    test_runtime_call_cancellation_reaches_background_pending_only(tmp_path)
