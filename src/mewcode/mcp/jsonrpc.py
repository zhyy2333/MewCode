from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Callable

from .models import (
    McpDiagnostic,
    McpError,
    McpPhase,
    McpProtocolError,
    McpRequestTimeout,
    McpUnavailableError,
)
from .transport import JsonRpcMessage, McpTransport


class JsonRpcPeer:
    def __init__(
        self,
        transport: McpTransport,
        request_timeout: float,
        id_factory: Callable[[], int] | None = None,
    ) -> None:
        self._transport = transport
        self._request_timeout = request_timeout
        self._next_id = 1
        self._id_factory = id_factory
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._failure: McpError | None = None
        self._started = False
        self._closed = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def failure(self) -> McpError | None:
        return self._failure

    async def start(self) -> None:
        if self._started:
            return
        await self._transport.start(self.receive, self.fail)
        self._started = True

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        self._ensure_available()
        request_id = self._allocate_id()
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message: JsonRpcMessage = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        try:
            async with asyncio.timeout(timeout or self._request_timeout):
                await self._transport.send(message)
                return await future
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            await self._best_effort_cancel(request_id, "request timed out")
            raise McpRequestTimeout(
                self._transport.server_name,
                McpPhase.CALL,
                "MCP request timed out.",
            ) from exc
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            await self._best_effort_cancel(request_id, "request cancelled")
            raise
        except McpError as exc:
            self._pending.pop(request_id, None)
            if exc.session_fatal:
                await self.fail(exc)
            raise
        except Exception as exc:
            self._pending.pop(request_id, None)
            error = McpProtocolError(
                self._transport.server_name,
                McpPhase.CALL,
                "MCP request could not be completed.",
                session_fatal=True,
            )
            await self.fail(error)
            raise error from exc
        finally:
            if future.cancelled():
                self._pending.pop(request_id, None)

    async def notify(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        self._ensure_available()
        message: JsonRpcMessage = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._transport.send(message)

    async def receive(self, message: JsonRpcMessage) -> None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            await self._protocol_failure("Invalid JSON-RPC envelope.")
            return
        has_method = isinstance(message.get("method"), str)
        has_id = "id" in message
        if has_method:
            if has_id:
                await self._handle_server_request(message)
            return
        if not has_id:
            await self._protocol_failure("JSON-RPC response is missing an id.")
            return
        response_id = message.get("id")
        if not isinstance(response_id, int) or isinstance(response_id, bool):
            await self._protocol_failure("JSON-RPC response id is invalid.")
            return
        future = self._pending.get(response_id)
        if future is None:
            return
        has_result = "result" in message
        has_error = "error" in message
        if has_result == has_error:
            await self._protocol_failure("JSON-RPC response must contain result or error.")
            return
        self._pending.pop(response_id, None)
        if has_error:
            error = message["error"]
            code = error.get("code") if isinstance(error, dict) else None
            future.set_exception(
                McpProtocolError(
                    self._transport.server_name,
                    McpPhase.CALL,
                    f"MCP request failed with JSON-RPC code {code}.",
                )
            )
        else:
            future.set_result(message["result"])

    async def fail(self, error: McpError) -> None:
        if self._failure is None:
            self._failure = error
        pending = tuple(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(self._failure)

    async def close(self) -> tuple[McpDiagnostic, ...]:
        if self._closed:
            return ()
        self._closed = True
        await self.fail(
            self._failure
            or McpUnavailableError(
                self._transport.server_name,
                McpPhase.SHUTDOWN,
                "MCP session is closed.",
                session_fatal=True,
            )
        )
        return await self._transport.close()

    def _allocate_id(self) -> int:
        if self._id_factory is not None:
            return self._id_factory()
        value = self._next_id
        self._next_id += 1
        return value

    def _ensure_available(self) -> None:
        if self._closed or self._failure is not None:
            raise self._failure or McpUnavailableError(
                self._transport.server_name,
                McpPhase.CALL,
                "MCP session is unavailable.",
                session_fatal=True,
            )

    async def _handle_server_request(self, message: JsonRpcMessage) -> None:
        request_id = message["id"]
        if message["method"] == "ping":
            response = {"jsonrpc": "2.0", "id": request_id, "result": {}}
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        try:
            await self._transport.send(response)
        except McpError as exc:
            if exc.session_fatal:
                await self.fail(exc)

    async def _protocol_failure(self, message: str) -> None:
        await self.fail(
            McpProtocolError(
                self._transport.server_name,
                McpPhase.CALL,
                message,
                session_fatal=True,
            )
        )

    async def _best_effort_cancel(self, request_id: int, reason: str) -> None:
        if self._closed or self._failure is not None:
            return
        with suppress(Exception, asyncio.CancelledError):
            await asyncio.wait_for(
                asyncio.shield(
                    self.notify(
                        "notifications/cancelled",
                        {"requestId": request_id, "reason": reason},
                    )
                ),
                timeout=min(1.0, max(0.01, self._request_timeout)),
            )

