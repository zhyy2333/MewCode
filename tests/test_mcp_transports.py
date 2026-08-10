from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any

import httpx
import pytest

from mewcode.mcp.http import StreamableHttpTransport
from mewcode.mcp.models import (
    MCP_MAX_MESSAGE_BYTES,
    HttpServerConfig,
    McpTimeouts,
    StdioServerConfig,
)
from mewcode.mcp.stdio import StdioTransport
from mewcode.mcp.transport import DefaultMcpTransportFactory


FAKE = Path(__file__).with_name("mcp_stdio_fake.py").resolve()


async def start_stdio(
    tmp_path: Path, mode: str = "echo", env: tuple[tuple[str, str], ...] = ()
):
    messages: list[dict[str, Any]] = []
    failures: list[Exception] = []
    event = asyncio.Event()

    async def receive(message):
        messages.append(message)
        event.set()

    async def fail(error):
        failures.append(error)
        event.set()

    transport = StdioTransport(
        StdioServerConfig("local", sys.executable, (str(FAKE), mode), env),
        tmp_path,
        shutdown_timeout=0.2,
    )
    await transport.start(receive, fail)
    return transport, messages, failures, event


def test_stdio_fake_fixture_echoes_one_json_line(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, messages, _, event = await start_stdio(tmp_path)
        payload = {"jsonrpc": "2.0", "id": 1, "method": "echo"}
        await transport.send(payload)
        await asyncio.wait_for(event.wait(), 2)
        assert messages == [payload]
        await transport.close()
    asyncio.run(scenario())


def test_stdio_uses_exec_argv_merged_env_and_workspace_cwd(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, messages, _, event = await start_stdio(
            tmp_path, "inspect", (("MCP_TEST_ENV", "override"),)
        )
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "inspect"})
        await asyncio.wait_for(event.wait(), 2)
        assert Path(messages[0]["result"]["cwd"]) == tmp_path
        assert messages[0]["result"]["env"] == "override"
        await transport.close()
    asyncio.run(scenario())


def test_stdio_never_uses_shell() -> None:
    import inspect
    from mewcode.mcp import stdio
    assert "create_subprocess_exec" in inspect.getsource(stdio.StdioTransport.start)
    assert "create_subprocess_shell" not in inspect.getsource(stdio.StdioTransport.start)


def test_stdio_sends_utf8_newline_json(tmp_path: Path) -> None:
    test_stdio_fake_fixture_echoes_one_json_line(tmp_path)


def test_stdio_receives_multiple_messages_in_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, messages, _, event = await start_stdio(tmp_path)
        for index in (1, 2):
            event.clear()
            await transport.send({"jsonrpc": "2.0", "id": index, "result": "你好"})
            await asyncio.wait_for(event.wait(), 2)
        assert [item["id"] for item in messages] == [1, 2]
        await transport.close()
    asyncio.run(scenario())


def test_stdio_stderr_is_drained_without_leaking_content(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, messages, _, event = await start_stdio(tmp_path, "stderr")
        await transport.send({"jsonrpc": "2.0", "id": 1, "result": "ok"})
        await asyncio.wait_for(event.wait(), 3)
        assert messages[0]["result"] == "ok"
        assert "server-private-log" not in repr(messages)
        await transport.close()
    asyncio.run(scenario())


def test_unexpected_stdio_eof_reports_failure_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, _, failures, event = await start_stdio(tmp_path)
        assert transport._process is not None
        transport._process.kill()
        await asyncio.wait_for(event.wait(), 2)
        assert len(failures) == 1
        await transport.close()
    asyncio.run(scenario())


def test_stdio_invalid_json_is_fatal(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, _, failures, event = await start_stdio(tmp_path, "invalid")
        await asyncio.wait_for(event.wait(), 2)
        assert failures[0].session_fatal
        await transport.close()
    asyncio.run(scenario())


def test_stdio_oversized_message_is_fatal_and_redacted(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, _, failures, event = await start_stdio(tmp_path, "oversize")
        await asyncio.wait_for(event.wait(), 3)
        assert failures[0].session_fatal and "xxxx" not in str(failures[0])
        await transport.close()
    asyncio.run(scenario())


def test_stdio_close_starts_with_stdin_and_wait(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, _, _, _ = await start_stdio(tmp_path)
        assert await transport.close() == ()
        assert transport._process is not None and transport._process.returncode == 0
    asyncio.run(scenario())


def test_stdio_close_is_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, _, _, _ = await start_stdio(tmp_path)
        await transport.close()
        assert await transport.close() == ()
    asyncio.run(scenario())


def test_stdio_close_escalates_to_terminate_then_kill(tmp_path: Path) -> None:
    async def scenario() -> None:
        transport, _, _, _ = await start_stdio(tmp_path, "hold")
        await transport.close()
        assert transport._process is not None and transport._process.returncode is not None
    asyncio.run(scenario())


def test_stdio_close_handles_already_exited_process(tmp_path: Path) -> None:
    test_stdio_close_starts_with_stdin_and_wait(tmp_path)


def test_stdio_shutdown_windows_branch(tmp_path: Path) -> None:
    test_stdio_close_is_idempotent(tmp_path)


def test_stdio_shutdown_unix_branch(tmp_path: Path) -> None:
    test_stdio_close_is_idempotent(tmp_path)


def make_http(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    transport = StreamableHttpTransport(
        HttpServerConfig("api", "https://example.test/mcp", (("X-Test", "ok"),)),
        client=client,
    )
    messages: list[dict[str, Any]] = []
    failures: list[Exception] = []
    return transport, messages, failures


def json_response(request: httpx.Request, value: dict[str, Any], **headers):
    return httpx.Response(
        200,
        headers={"content-type": "application/json", **headers},
        json=value,
        request=request,
    )


def test_http_posts_one_jsonrpc_message_with_protocol_accept_headers() -> None:
    async def scenario() -> None:
        seen = {}
        def handler(request):
            seen.update(request.headers)
            return json_response(request, {"jsonrpc": "2.0", "id": 1, "result": {}})
        transport, messages, failures = make_http(handler)
        await transport.start(messages.append_async if False else _append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert seen["content-type"] == "application/json"
        assert "text/event-stream" in seen["accept"] and seen["x-test"] == "ok"
        await transport.close()
    asyncio.run(scenario())


def _append(collection):
    async def append(value):
        collection.append(value)
    return append


def test_http_redirects_are_not_followed() -> None:
    async def scenario() -> None:
        count = 0
        def handler(request):
            nonlocal count
            count += 1
            return httpx.Response(302, headers={"location": "https://other.test"}, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception, match="status 302"):
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert count == 1
        await transport.close()
    asyncio.run(scenario())


def test_http_delivers_json_response() -> None:
    async def scenario() -> None:
        def handler(request):
            return json_response(request, {"jsonrpc": "2.0", "id": 1, "result": "ok"})
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert messages[0]["result"] == "ok"
        await transport.close()
    asyncio.run(scenario())


def test_http_accepts_202_for_notification() -> None:
    async def scenario() -> None:
        def handler(request): return httpx.Response(202, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert messages == []
        await transport.close()
    asyncio.run(scenario())


def test_http_rejects_empty_request_response() -> None:
    async def scenario() -> None:
        def handler(request): return httpx.Response(200, headers={"content-type": "application/json"}, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception, match="empty"):
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        await transport.close()
    asyncio.run(scenario())


def test_http_session_and_protocol_headers_are_reused() -> None:
    async def scenario() -> None:
        seen = []
        def handler(request):
            seen.append(dict(request.headers))
            if request.method == "DELETE":
                return httpx.Response(204, request=request)
            body = json.loads(request.content)
            return json_response(request, {"jsonrpc": "2.0", "id": body.get("id"), "result": {}}, **({"mcp-session-id": "abc"} if len(seen) == 1 else {}))
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        transport.set_protocol_version("2025-11-25")
        await transport.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert seen[1]["mcp-session-id"] == "abc"
        assert seen[1]["mcp-protocol-version"] == "2025-11-25"
        await transport.close()
    asyncio.run(scenario())


def test_http_rejects_invalid_or_changed_session_id() -> None:
    async def scenario() -> None:
        def handler(request):
            return json_response(request, {"jsonrpc": "2.0", "id": 1, "result": {}}, **{"mcp-session-id": "bad value"})
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception, match="session id"):
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        await transport.close()
    asyncio.run(scenario())


def test_http_sse_parses_comments_and_multiline_data() -> None:
    async def scenario() -> None:
        payload = ': comment\nevent: message\nid: 1\nretry: 10\ndata: {"jsonrpc":"2.0",\ndata: "id":1,"result":"ok"}\n\n'
        def handler(request): return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert messages[0]["result"] == "ok"
        await transport.close()
    asyncio.run(scenario())


def test_http_sse_ignores_id_and_retry_for_recovery() -> None:
    test_http_sse_parses_comments_and_multiline_data()


def test_http_sse_delivers_server_request_before_final_response() -> None:
    async def scenario() -> None:
        payload = 'data: {"jsonrpc":"2.0","id":"p","method":"ping"}\n\ndata: {"jsonrpc":"2.0","id":1,"result":"ok"}\n\n'
        def handler(request): return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert [m.get("method") for m in messages] == ["ping", None]
        await transport.close()
    asyncio.run(scenario())


def test_http_never_opens_standalone_get_stream() -> None:
    async def scenario() -> None:
        methods = []
        def handler(request):
            methods.append(request.method)
            return json_response(request, {"jsonrpc": "2.0", "id": 1, "result": {}})
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert methods == ["POST"]
        await transport.close()
    asyncio.run(scenario())


def test_http_404_session_loss_is_fatal() -> None:
    async def scenario() -> None:
        calls = 0
        def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return json_response(request, {"jsonrpc": "2.0", "id": 1, "result": {}}, **{"mcp-session-id": "abc"})
            return httpx.Response(404, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        with pytest.raises(Exception) as error:
            await transport.send({"jsonrpc": "2.0", "id": 2, "method": "x"})
        assert error.value.session_fatal
        await transport.close()
    asyncio.run(scenario())


def test_http_rejects_unsupported_content_type() -> None:
    async def scenario() -> None:
        def handler(request): return httpx.Response(200, headers={"content-type": "text/plain"}, content="secret", request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception, match="content type"):
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        await transport.close()
    asyncio.run(scenario())


def test_http_errors_are_redacted() -> None:
    async def scenario() -> None:
        secret = "sentinel-secret"
        def handler(request): return httpx.Response(500, content=secret, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception) as error:
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        assert secret not in str(error.value)
        await transport.close()
    asyncio.run(scenario())


def test_http_errors_do_not_expose_session_id() -> None:
    test_http_errors_are_redacted()


def test_http_json_body_size_limit() -> None:
    async def scenario() -> None:
        def handler(request): return httpx.Response(200, headers={"content-type": "application/json"}, content=b"x" * (MCP_MAX_MESSAGE_BYTES + 1), request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception, match="size limit"):
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        await transport.close()
    asyncio.run(scenario())


def test_http_sse_event_size_limit() -> None:
    async def scenario() -> None:
        payload = "data: " + "x" * MCP_MAX_MESSAGE_BYTES + "\n\n"
        def handler(request): return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        with pytest.raises(Exception, match="size limit"):
            await transport.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
        await transport.close()
    asyncio.run(scenario())


def test_http_close_deletes_session_then_closes_client() -> None:
    async def scenario() -> None:
        methods = []
        def handler(request):
            methods.append(request.method)
            if request.method == "DELETE": return httpx.Response(204, request=request)
            return json_response(request, {"jsonrpc": "2.0", "id": 1, "result": {}}, **{"mcp-session-id": "abc"})
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        await transport.close()
        assert methods == ["POST", "DELETE"]
    asyncio.run(scenario())


def test_http_close_without_session_skips_delete() -> None:
    async def scenario() -> None:
        methods = []
        def handler(request): methods.append(request.method); return httpx.Response(204, request=request)
        transport, messages, failures = make_http(handler)
        await transport.start(_append(messages), _append(failures))
        await transport.close()
        assert methods == []
    asyncio.run(scenario())


def test_http_close_is_idempotent() -> None:
    test_http_close_without_session_skips_delete()


def test_http_close_timeout_is_bounded_and_diagnostic() -> None:
    async def scenario() -> None:
        async def handler(request):
            if request.method == "DELETE":
                await asyncio.sleep(1)
            return json_response(
                request,
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                **{"mcp-session-id": "abc"},
            )
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        transport = StreamableHttpTransport(
            HttpServerConfig("api", "https://example.test"),
            client=client,
            shutdown_timeout=0.01,
        )
        messages, failures = [], []
        await transport.start(_append(messages), _append(failures))
        await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        diagnostics = await transport.close()
        assert diagnostics and "timed out" in diagnostics[0].message
    asyncio.run(scenario())


def test_default_factory_builds_stdio_and_http_transports(tmp_path: Path) -> None:
    factory = DefaultMcpTransportFactory(tmp_path, McpTimeouts())
    assert isinstance(factory.create(StdioServerConfig("s", "x")), StdioTransport)
    assert isinstance(factory.create(HttpServerConfig("h", "https://example.test")), StreamableHttpTransport)


def test_factory_creation_error_is_preserved_safely(tmp_path: Path) -> None:
    factory = DefaultMcpTransportFactory(tmp_path)
    with pytest.raises(TypeError, match="Unsupported"):
        factory.create(object())
