from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Mapping, Protocol

import httpx

from .models import (
    HttpServerConfig,
    McpDiagnostic,
    McpError,
    McpServerConfig,
    McpTimeouts,
    StdioServerConfig,
)

JsonRpcMessage = dict[str, Any]
MessageHandler = Callable[[JsonRpcMessage], Awaitable[None]]
FailureHandler = Callable[[McpError], Awaitable[None]]


class McpTransport(Protocol):
    server_name: str

    async def start(
        self, on_message: MessageHandler, on_failure: FailureHandler
    ) -> None: ...

    async def send(self, message: JsonRpcMessage) -> None: ...
    def set_protocol_version(self, version: str) -> None: ...
    async def close(self) -> tuple[McpDiagnostic, ...]: ...


class McpTransportFactory(Protocol):
    def create(self, config: McpServerConfig) -> McpTransport: ...


class DefaultMcpTransportFactory:
    def __init__(
        self,
        workspace_root: Path,
        timeouts: McpTimeouts | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._timeouts = timeouts or McpTimeouts()
        self._http_client_factory = http_client_factory
        self._environment_overrides = dict(environment_overrides or {})

    def create(self, config: McpServerConfig) -> McpTransport:
        if isinstance(config, StdioServerConfig):
            from .stdio import StdioTransport

            return StdioTransport(
                config,
                self._workspace_root,
                shutdown_timeout=self._timeouts.shutdown_seconds,
                environment_overrides=self._environment_overrides,
            )
        if isinstance(config, HttpServerConfig):
            from .http import StreamableHttpTransport

            client = self._http_client_factory() if self._http_client_factory else None
            return StreamableHttpTransport(
                config,
                client=client,
                shutdown_timeout=self._timeouts.shutdown_seconds,
            )
        raise TypeError("Unsupported MCP server configuration.")
