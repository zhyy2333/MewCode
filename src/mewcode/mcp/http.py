from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from typing import Any

import httpx

from .models import (
    MCP_MAX_MESSAGE_BYTES,
    HttpServerConfig,
    McpDiagnostic,
    McpPhase,
    McpTransportError,
)
from .transport import FailureHandler, MessageHandler


class StreamableHttpTransport:
    def __init__(
        self,
        config: HttpServerConfig,
        *,
        client: httpx.AsyncClient | None = None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        self.server_name = config.name
        self._url = config.url
        self._user_headers = dict(config.headers)
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=None,
        )
        self._shutdown_timeout = shutdown_timeout
        self._on_message: MessageHandler | None = None
        self._on_failure: FailureHandler | None = None
        self._protocol_version: str | None = None
        self._session_id: str | None = None
        self._started = False
        self._closed = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def start(
        self, on_message: MessageHandler, on_failure: FailureHandler
    ) -> None:
        self._on_message = on_message
        self._on_failure = on_failure
        self._started = True

    async def send(self, message: dict[str, Any]) -> None:
        if self._closed or not self._started:
            raise self._error("MCP HTTP transport is unavailable.", fatal=True)
        try:
            payload = json.dumps(
                message, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise self._error("MCP message is not JSON serializable.") from exc
        if len(payload) > MCP_MAX_MESSAGE_BYTES:
            raise self._error("MCP message exceeds the size limit.", fatal=True)
        try:
            async with self._client.stream(
                "POST", self._url, headers=self._headers(), content=payload
            ) as response:
                self._capture_session(response)
                if response.status_code == 202:
                    await response.aread()
                    return
                if response.status_code == 404 and self._session_id is not None:
                    raise self._error("MCP HTTP session is no longer available.", fatal=True)
                if not 200 <= response.status_code < 300:
                    raise self._error(
                        f"MCP HTTP request failed with status {response.status_code}."
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type == "application/json":
                    await self._read_json(response)
                    return
                if content_type == "text/event-stream":
                    await self._read_sse(response)
                    return
                raise self._error("MCP HTTP response has an unsupported content type.")
        except McpTransportError:
            raise
        except httpx.HTTPError as exc:
            raise self._error("MCP HTTP request failed.") from exc

    def set_protocol_version(self, version: str) -> None:
        self._protocol_version = version

    async def close(self) -> tuple[McpDiagnostic, ...]:
        if self._closed:
            return ()
        diagnostics: list[McpDiagnostic] = []
        async def cleanup() -> None:
            if self._session_id is not None:
                response = await self._client.delete(
                    self._url, headers=self._headers()
                )
                if response.status_code not in {200, 202, 204, 405}:
                    diagnostics.append(
                        McpDiagnostic(
                            self.server_name,
                            McpPhase.SHUTDOWN,
                            f"HTTP session close returned status {response.status_code}",
                        )
                    )
            await self._client.aclose()

        try:
            await asyncio.wait_for(cleanup(), self._shutdown_timeout)
        except (TimeoutError, httpx.HTTPError):
            diagnostics.append(
                McpDiagnostic(
                    self.server_name,
                    McpPhase.SHUTDOWN,
                    "HTTP session close failed or timed out",
                )
            )
            with suppress(Exception):
                await asyncio.wait_for(self._client.aclose(), 0.1)
        self._closed = True
        return tuple(diagnostics)

    def _headers(self) -> dict[str, str]:
        headers = dict(self._user_headers)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json, text/event-stream"
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        if self._session_id is not None:
            headers["MCP-Session-Id"] = self._session_id
        return headers

    def _capture_session(self, response: httpx.Response) -> None:
        value = response.headers.get("mcp-session-id")
        if value is None:
            return
        if not value or any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
            raise self._error("MCP HTTP server returned an invalid session id.", fatal=True)
        if self._session_id is not None and value != self._session_id:
            raise self._error("MCP HTTP server changed the session id.", fatal=True)
        self._session_id = value

    async def _read_json(self, response: httpx.Response) -> None:
        payload = await self._bounded_body(response)
        if not payload:
            raise self._error("MCP HTTP request returned an empty response.")
        try:
            message = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise self._error("MCP HTTP server returned invalid JSON.", fatal=True) from exc
        await self._deliver(message)

    async def _read_sse(self, response: httpx.Response) -> None:
        data_lines: list[str] = []
        size = 0
        async for line in response.aiter_lines():
            encoded_size = len(line.encode("utf-8")) + 1
            size += encoded_size
            if size > MCP_MAX_MESSAGE_BYTES:
                raise self._error("MCP SSE event exceeds the size limit.", fatal=True)
            if line == "":
                if data_lines:
                    await self._deliver_sse_data("\n".join(data_lines))
                data_lines = []
                size = 0
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                data_lines.append(value)
        if data_lines:
            await self._deliver_sse_data("\n".join(data_lines))

    async def _deliver_sse_data(self, data: str) -> None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError as exc:
            raise self._error("MCP SSE event contains invalid JSON.", fatal=True) from exc
        await self._deliver(message)

    async def _deliver(self, message: Any) -> None:
        if not isinstance(message, dict):
            raise self._error("MCP HTTP message must be a JSON object.", fatal=True)
        assert self._on_message is not None
        await self._on_message(message)

    async def _bounded_body(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MCP_MAX_MESSAGE_BYTES:
                raise self._error("MCP HTTP response exceeds the size limit.", fatal=True)
            chunks.append(chunk)
        return b"".join(chunks)

    def _error(self, message: str, *, fatal: bool = False) -> McpTransportError:
        return McpTransportError(
            self.server_name,
            McpPhase.CALL,
            message,
            session_fatal=fatal,
        )
