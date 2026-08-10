from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mewcode.mcp.jsonrpc import JsonRpcPeer
from mewcode.mcp.models import McpPhase, McpProtocolError, McpTransportError


class MemoryTransport:
    server_name = "server"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.on_message = None
        self.on_failure = None
        self.closed = 0

    async def start(self, on_message, on_failure) -> None:
        self.on_message = on_message
        self.on_failure = on_failure

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    def set_protocol_version(self, version: str) -> None:
        pass

    async def close(self):
        self.closed += 1
        return ()


async def started(timeout: float = 1) -> tuple[MemoryTransport, JsonRpcPeer]:
    transport = MemoryTransport()
    peer = JsonRpcPeer(transport, timeout)
    await peer.start()
    return transport, peer


def test_request_uses_incrementing_integer_ids() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        one = asyncio.create_task(peer.request("one"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 1, "result": 1})
        two = asyncio.create_task(peer.request("two"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 2, "result": 2})
        assert await one == 1 and await two == 2
        assert [message["id"] for message in transport.sent] == [1, 2]
    asyncio.run(scenario())


def test_notification_has_no_id() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        await peer.notify("notifications/initialized")
        assert "id" not in transport.sent[0]
    asyncio.run(scenario())


def test_out_of_order_responses_pair_by_id() -> None:
    async def scenario() -> None:
        _, peer = await started()
        first = asyncio.create_task(peer.request("first"))
        second = asyncio.create_task(peer.request("second"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 2, "result": "second"})
        await peer.receive({"jsonrpc": "2.0", "id": 1, "result": "first"})
        assert await asyncio.gather(first, second) == ["first", "second"]
    asyncio.run(scenario())


def test_completed_request_is_removed_from_pending() -> None:
    async def scenario() -> None:
        _, peer = await started()
        task = asyncio.create_task(peer.request("x"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 1, "result": {}})
        await task
        assert peer.pending_count == 0
    asyncio.run(scenario())


def test_jsonrpc_error_completes_matching_request() -> None:
    async def scenario() -> None:
        _, peer = await started()
        task = asyncio.create_task(peer.request("x"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "secret"}})
        with pytest.raises(McpProtocolError, match="code -1"):
            await task
    asyncio.run(scenario())


def test_unknown_and_duplicate_ids_are_ignored() -> None:
    async def scenario() -> None:
        _, peer = await started()
        task = asyncio.create_task(peer.request("x"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 999, "result": "wrong"})
        await peer.receive({"jsonrpc": "2.0", "id": 1, "result": "right"})
        await peer.receive({"jsonrpc": "2.0", "id": 1, "result": "duplicate"})
        assert await task == "right"
    asyncio.run(scenario())


def test_untrustworthy_response_fails_peer() -> None:
    async def scenario() -> None:
        _, peer = await started()
        task = asyncio.create_task(peer.request("x"))
        await asyncio.sleep(0)
        await peer.receive({"jsonrpc": "2.0", "id": 1})
        with pytest.raises(McpProtocolError):
            await task
        assert peer.failure is not None
    asyncio.run(scenario())


def test_request_timeout_only_fails_that_pending_call() -> None:
    async def scenario() -> None:
        _, peer = await started(0.01)
        with pytest.raises(Exception, match="timed out"):
            await peer.request("slow")
        assert peer.pending_count == 0 and peer.failure is None
    asyncio.run(scenario())


def test_timeout_sends_cancelled_notification_when_writable() -> None:
    async def scenario() -> None:
        transport, peer = await started(0.01)
        with pytest.raises(Exception):
            await peer.request("slow")
        assert transport.sent[-1]["method"] == "notifications/cancelled"
        assert transport.sent[-1]["params"]["requestId"] == 1
    asyncio.run(scenario())


def test_late_response_after_timeout_is_ignored() -> None:
    async def scenario() -> None:
        _, peer = await started(0.01)
        with pytest.raises(Exception):
            await peer.request("slow")
        await peer.receive({"jsonrpc": "2.0", "id": 1, "result": "late"})
        assert peer.failure is None
    asyncio.run(scenario())


def test_cancelled_request_is_removed_without_affecting_others() -> None:
    async def scenario() -> None:
        _, peer = await started()
        one = asyncio.create_task(peer.request("one"))
        two = asyncio.create_task(peer.request("two"))
        await asyncio.sleep(0)
        one.cancel()
        with pytest.raises(asyncio.CancelledError):
            await one
        await peer.receive({"jsonrpc": "2.0", "id": 2, "result": "ok"})
        assert await two == "ok"
    asyncio.run(scenario())


def test_caller_cancellation_sends_cancelled_notification_best_effort() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        task = asyncio.create_task(peer.request("one"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert any(m.get("method") == "notifications/cancelled" for m in transport.sent)
    asyncio.run(scenario())


def test_ping_request_receives_empty_result() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        await peer.receive({"jsonrpc": "2.0", "id": "ping", "method": "ping"})
        assert transport.sent[-1] == {"jsonrpc": "2.0", "id": "ping", "result": {}}
    asyncio.run(scenario())


def test_unknown_server_request_receives_method_not_found() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        await peer.receive({"jsonrpc": "2.0", "id": 9, "method": "resources/read"})
        assert transport.sent[-1]["error"]["code"] == -32601
    asyncio.run(scenario())


def test_unknown_notification_is_ignored() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        await peer.receive({"jsonrpc": "2.0", "method": "notifications/unknown"})
        assert transport.sent == [] and peer.failure is None
    asyncio.run(scenario())


def test_transport_failure_completes_all_pending() -> None:
    async def scenario() -> None:
        _, peer = await started()
        tasks = [asyncio.create_task(peer.request(str(i))) for i in range(2)]
        await asyncio.sleep(0)
        await peer.fail(McpTransportError("server", McpPhase.CALL, "gone", session_fatal=True))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(value, McpTransportError) for value in results)
        assert peer.pending_count == 0
    asyncio.run(scenario())


def test_closed_peer_fails_fast() -> None:
    async def scenario() -> None:
        _, peer = await started()
        await peer.close()
        with pytest.raises(Exception, match="closed"):
            await peer.request("x")
    asyncio.run(scenario())


def test_peer_close_is_idempotent() -> None:
    async def scenario() -> None:
        transport, peer = await started()
        await peer.close()
        await peer.close()
        assert transport.closed == 1
    asyncio.run(scenario())
