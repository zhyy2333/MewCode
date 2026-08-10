from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import httpx

from mewcode.mcp.config import McpConfigLoader, McpConfigPaths
from mewcode.mcp.models import HttpServerConfig, McpTimeouts, StdioServerConfig
from mewcode.mcp.runtime import McpRuntime
from mewcode.mcp.transport import DefaultMcpTransportFactory


FAKE = Path(__file__).with_name("mcp_stdio_fake.py").resolve()


def test_stdio_full_flow_from_merged_config_to_final_answer_and_cleanup(tmp_path: Path) -> None:
    user = tmp_path / "user.yaml"
    project = tmp_path / "project.yaml"
    user.write_text(
        f"""mcp_servers:
  old: {{transport: stdio, command: ignored}}
  local: {{transport: stdio, command: ignored-user, env: {{OLD: value}}}}
""",
        encoding="utf-8",
    )
    project.write_text(
        f"""mcp_servers:
  local:
    transport: stdio
    command: '{sys.executable}'
    args: ['{FAKE.as_posix()}', mcp]
""",
        encoding="utf-8",
    )
    loaded = McpConfigLoader().load(McpConfigPaths(user, project))
    local = tuple(server for server in loaded.servers if server.name == "local")
    runtime = McpRuntime(tmp_path, timeouts=McpTimeouts(2, 2, 1))
    started = runtime.start(local, set())
    assert len(started.tools) == 1
    tool = started.tools[0]

    async def calls():
        first = await tool.execute({"value": "one"})
        second = await tool.execute({"value": "two"})
        return first, second

    first, second = asyncio.run(calls())
    pid1, count1, value1 = first.content.split(":")
    pid2, count2, value2 = second.content.split(":")
    final_answer = f"Received {value1} and {value2}."
    assert pid1 == pid2 and (count1, count2) == ("1", "2")
    assert final_answer == "Received one and two."
    assert runtime.close() == ()
    assert runtime._thread is not None and not runtime._thread.is_alive()


class HttpScript:
    def __init__(self, *, parity: bool = False):
        self.requests: list[tuple[str, dict, dict]] = []
        self.call_count = 0
        self.parity = parity

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            self.requests.append(("DELETE", {}, dict(request.headers)))
            return httpx.Response(204, request=request)
        body = json.loads(request.content)
        self.requests.append(("POST", body, dict(request.headers)))
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json", "mcp-session-id": "session-1"},
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "http-fake", "version": "1"},
                    },
                },
                request=request,
            )
        if method == "notifications/initialized":
            return httpx.Response(202, request=request)
        if method == "tools/list":
            data = json.dumps({
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"tools": [{"name": "echo.remote", "description": "Echo", "inputSchema": {"type": "object"}}]},
            }, separators=(",", ":"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    'data: {"jsonrpc":"2.0","id":"ping-1","method":"ping"}\n\n'
                    f": ready\ndata: {data}\n\n"
                ),
                request=request,
            )
        if method == "tools/call":
            self.call_count += 1
            value = body["params"]["arguments"].get("value", "")
            output = f"ok:{value}" if self.parity else f"http:{self.call_count}:{value}"
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": output}]}},
                request=request,
            )
        return httpx.Response(202, request=request)


def http_runtime(tmp_path: Path, script: HttpScript):
    factory = DefaultMcpTransportFactory(
        tmp_path,
        McpTimeouts(2, 2, 1),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(script), follow_redirects=False
        ),
    )
    runtime = McpRuntime(
        tmp_path,
        timeouts=McpTimeouts(2, 2, 1),
        transport_factory=factory,
    )
    started = runtime.start(
        (HttpServerConfig("api", "https://example.test/mcp", (("Authorization", "Bearer expanded"),)),),
        set(),
    )
    return runtime, started.tools[0]


def test_http_full_flow_from_env_header_to_final_answer_and_session_delete(tmp_path: Path) -> None:
    script = HttpScript()
    runtime, tool = http_runtime(tmp_path, script)
    execution = asyncio.run(tool.execute({"value": "hello"}))
    final_answer = f"Final: {execution.content}"
    assert final_answer == "Final: http:1:hello"
    runtime.close()
    posts = [entry for entry in script.requests if entry[0] == "POST"]
    assert all(entry[2].get("authorization") == "Bearer expanded" for entry in posts)
    assert any(entry[2].get("mcp-session-id") == "session-1" for entry in posts[1:])
    assert all(method != "GET" for method, _, _ in script.requests)
    assert script.requests[-1][0] == "DELETE"


def test_same_protocol_scenario_matches_across_stdio_and_http(tmp_path: Path) -> None:
    stdio_runtime = McpRuntime(tmp_path, timeouts=McpTimeouts(2, 2, 1))
    stdio_started = stdio_runtime.start(
        (StdioServerConfig("shared", sys.executable, (str(FAKE), "mcp-parity")),),
        set(),
    )
    script = HttpScript(parity=True)
    factory = DefaultMcpTransportFactory(
        tmp_path,
        McpTimeouts(2, 2, 1),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(script), follow_redirects=False
        ),
    )
    http_side = McpRuntime(tmp_path, transport_factory=factory)
    http_started = http_side.start(
        (HttpServerConfig("shared", "https://example.test/mcp"),), set()
    )
    stdio_result = asyncio.run(stdio_started.tools[0].execute({"value": "same"}))
    http_result = asyncio.run(http_started.tools[0].execute({"value": "same"}))
    assert stdio_started.tools[0].name == http_started.tools[0].name
    assert stdio_result == http_result
    stdio_runtime.close(); http_side.close()


def test_mixed_server_failures_are_isolated_and_never_reconnect(tmp_path: Path) -> None:
    class MixedFactory:
        def __init__(self): self.good = HttpScript(); self.counts = {"bad": 0, "good": 0}
        def create(self, config):
            self.counts[config.name] += 1
            if config.name == "bad":
                raise RuntimeError("sentinel-secret")
            client = httpx.AsyncClient(transport=httpx.MockTransport(self.good), follow_redirects=False)
            from mewcode.mcp.http import StreamableHttpTransport
            return StreamableHttpTransport(HttpServerConfig("good", "https://example.test"), client=client)
    factory = MixedFactory()
    runtime = McpRuntime(tmp_path, timeouts=McpTimeouts(.2, .2, .2), transport_factory=factory)
    started = runtime.start((HttpServerConfig("bad", "https://bad.test"), HttpServerConfig("good", "https://good.test")), set())
    assert len(started.tools) == 1
    assert started.tools[0].name.startswith("good__echo_remote_")
    assert "sentinel-secret" not in repr(started.diagnostics)
    result = asyncio.run(started.tools[0].execute({"value": "ok"}))
    assert result.ok and factory.counts == {"bad": 1, "good": 1}
    runtime.close()


def test_recoverable_mcp_call_errors_do_not_stop_later_agent_calls(tmp_path: Path) -> None:
    from mewcode.mcp.models import (
        McpCallResult,
        McpPhase,
        McpProtocolError,
        McpRequestTimeout,
        McpToolDescriptor,
        McpTransportError,
        McpUnavailableError,
    )
    from mewcode.mcp.tool import McpTool

    class SequenceRuntime:
        def __init__(self):
            self.outcomes = [
                McpProtocolError("server", McpPhase.CALL, "JSON-RPC error"),
                McpTransportError("server", McpPhase.CALL, "HTTP error"),
                McpRequestTimeout("server", McpPhase.CALL, "timeout"),
                McpUnavailableError("server", McpPhase.CALL, "connection interrupted"),
                McpCallResult(False, ({"type": "text", "text": "recovered"},)),
            ]
        async def call_tool(self, server, tool, arguments):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    tool = McpTool(
        McpToolDescriptor("server", "remote", "server__remote", "", {}),
        SequenceRuntime(),
    )
    executions = [asyncio.run(tool.execute({})) for _ in range(5)]
    assert all(not execution.ok for execution in executions[:4])
    assert executions[-1].ok and executions[-1].content == "recovered"


def test_shutdown_leaves_no_mcp_process_client_pending_or_task(tmp_path: Path) -> None:
    script = HttpScript()
    runtime, _ = http_runtime(tmp_path, script)
    runtime.close()
    assert runtime._thread is not None and not runtime._thread.is_alive()
    assert runtime._manager is not None
    assert all(session._peer.pending_count == 0 for session in runtime._manager._sessions.values())
