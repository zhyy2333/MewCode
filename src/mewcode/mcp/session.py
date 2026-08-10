from __future__ import annotations

import asyncio
from typing import Any

from .jsonrpc import JsonRpcPeer
from .models import (
    MCP_PROTOCOL_VERSION,
    McpCallResult,
    McpDiagnostic,
    McpError,
    McpPhase,
    McpProtocolError,
    McpSessionState,
    McpTimeouts,
    McpUnavailableError,
)
from .transport import McpTransport


class McpClientSession:
    def __init__(
        self,
        server_name: str,
        transport: McpTransport,
        timeouts: McpTimeouts | None = None,
    ) -> None:
        self.server_name = server_name
        self._transport = transport
        self._timeouts = timeouts or McpTimeouts()
        self._peer = JsonRpcPeer(transport, self._timeouts.request_seconds)
        self.state = McpSessionState.NEW
        self.diagnostics: tuple[McpDiagnostic, ...] = ()

    async def start(self) -> tuple[dict[str, Any], ...]:
        if self.state != McpSessionState.NEW:
            raise self._unavailable("MCP session has already been started.")
        self.state = McpSessionState.STARTING
        try:
            async with asyncio.timeout(self._timeouts.startup_seconds):
                await self._peer.start()
                initialized = await self._peer.request(
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "mewcode", "version": "0.1.0"},
                    },
                    timeout=self._timeouts.startup_seconds,
                )
                self._validate_initialize(initialized)
                self._transport.set_protocol_version(MCP_PROTOCOL_VERSION)
                await self._peer.notify("notifications/initialized")
                tools = await self._list_all_tools()
            self.state = McpSessionState.READY
            return tools
        except TimeoutError as exc:
            self.state = McpSessionState.FAILED
            raise McpProtocolError(
                self.server_name,
                McpPhase.STARTUP,
                "MCP server startup timed out.",
                session_fatal=True,
            ) from exc
        except McpError:
            self.state = McpSessionState.FAILED
            raise
        except asyncio.CancelledError:
            self.state = McpSessionState.FAILED
            raise
        except Exception as exc:
            self.state = McpSessionState.FAILED
            raise McpProtocolError(
                self.server_name,
                McpPhase.STARTUP,
                "MCP server startup failed.",
                session_fatal=True,
            ) from exc

    async def call_tool(
        self, original_name: str, arguments: dict[str, Any]
    ) -> McpCallResult:
        if self.state != McpSessionState.READY or self._peer.failure is not None:
            if self._peer.failure is not None:
                self.state = McpSessionState.FAILED
            raise self._unavailable("MCP server is unavailable.")
        try:
            raw = await self._peer.request(
                "tools/call",
                {"name": original_name, "arguments": arguments},
                timeout=self._timeouts.request_seconds,
            )
            return self._parse_call_result(raw)
        except McpError as exc:
            if exc.session_fatal:
                self.state = McpSessionState.FAILED
            raise

    async def close(self) -> tuple[McpDiagnostic, ...]:
        if self.state == McpSessionState.CLOSED:
            return ()
        try:
            diagnostics = await self._peer.close()
        finally:
            self.state = McpSessionState.CLOSED
        return diagnostics

    def _validate_initialize(self, raw: Any) -> None:
        if not isinstance(raw, dict):
            raise self._protocol("Initialize result must be an object.")
        if raw.get("protocolVersion") != MCP_PROTOCOL_VERSION:
            raise self._protocol("MCP server returned an unsupported protocol version.")
        capabilities = raw.get("capabilities")
        server_info = raw.get("serverInfo")
        if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
            raise self._protocol("MCP server did not declare tools capability.")
        if not isinstance(server_info, dict) or not isinstance(server_info.get("name"), str):
            raise self._protocol("MCP serverInfo is invalid.")

    async def _list_all_tools(self) -> tuple[dict[str, Any], ...]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        diagnostics: list[McpDiagnostic] = []
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            raw = await self._peer.request(
                "tools/list", params, timeout=self._timeouts.startup_seconds
            )
            if not isinstance(raw, dict) or not isinstance(raw.get("tools"), list):
                raise self._protocol("tools/list result is invalid.")
            for tool in raw["tools"]:
                if self._valid_tool(tool):
                    tools.append(tool)
                else:
                    diagnostics.append(
                        McpDiagnostic(
                            self.server_name,
                            McpPhase.STARTUP,
                            "invalid tool definition was skipped",
                        )
                    )
            if "nextCursor" not in raw or raw["nextCursor"] is None:
                break
            next_cursor = raw["nextCursor"]
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in seen
            ):
                raise self._protocol("tools/list returned an invalid or repeated cursor.")
            seen.add(next_cursor)
            cursor = next_cursor
        self.diagnostics = tuple(diagnostics)
        return tuple(tools)

    @staticmethod
    def _valid_tool(raw: Any) -> bool:
        return (
            isinstance(raw, dict)
            and isinstance(raw.get("name"), str)
            and bool(raw["name"])
            and ("description" not in raw or isinstance(raw["description"], str))
            and isinstance(raw.get("inputSchema"), dict)
        )

    def _parse_call_result(self, raw: Any) -> McpCallResult:
        if not isinstance(raw, dict):
            raise self._protocol("tools/call result must be an object.", fatal=False)
        content = raw.get("content", [])
        is_error = raw.get("isError", False)
        structured = raw.get("structuredContent")
        if (
            not isinstance(content, list)
            or any(not isinstance(block, dict) for block in content)
            or not isinstance(is_error, bool)
            or (structured is not None and not isinstance(structured, dict))
        ):
            raise self._protocol("tools/call result is invalid.", fatal=False)
        return McpCallResult(is_error, tuple(content), structured)

    def _protocol(self, message: str, *, fatal: bool = True) -> McpProtocolError:
        return McpProtocolError(
            self.server_name,
            McpPhase.STARTUP if self.state == McpSessionState.STARTING else McpPhase.CALL,
            message,
            session_fatal=fatal,
        )

    def _unavailable(self, message: str) -> McpUnavailableError:
        return McpUnavailableError(
            self.server_name,
            McpPhase.CALL,
            message,
            session_fatal=True,
        )

