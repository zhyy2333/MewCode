from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

from mewcode.providers import ConfigError

MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class McpTransportKind(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


@dataclass(frozen=True)
class StdioServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class HttpServerConfig:
    name: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()


McpServerConfig: TypeAlias = StdioServerConfig | HttpServerConfig


class McpPhase(StrEnum):
    CONFIG = "config"
    STARTUP = "startup"
    CALL = "call"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class McpDiagnostic:
    server_name: str | None
    phase: McpPhase
    message: str


@dataclass(frozen=True)
class McpTimeouts:
    startup_seconds: float = 30.0
    request_seconds: float = 120.0
    shutdown_seconds: float = 5.0


class McpError(RuntimeError):
    def __init__(
        self,
        server_name: str,
        phase: McpPhase,
        safe_message: str,
        *,
        session_fatal: bool = False,
    ) -> None:
        self.server_name = server_name
        self.phase = phase
        self.safe_message = safe_message
        self.session_fatal = session_fatal
        super().__init__(safe_message)


class McpConfigError(ConfigError):
    pass


class McpTransportError(McpError):
    pass


class McpProtocolError(McpError):
    pass


class McpRequestTimeout(McpError):
    pass


class McpUnavailableError(McpError):
    pass


class McpSessionState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


class McpServerStartState(StrEnum):
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class McpServerStatus:
    server_name: str
    state: McpServerStartState
    tool_names: tuple[str, ...] = ()
    message: str | None = None


@dataclass(frozen=True)
class McpToolDescriptor:
    server_name: str
    original_name: str
    public_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class McpCallResult:
    is_error: bool
    content: tuple[dict[str, Any], ...]
    structured_content: dict[str, Any] | None = None


@dataclass(frozen=True)
class McpManagerStartResult:
    descriptors: tuple[McpToolDescriptor, ...]
    diagnostics: tuple[McpDiagnostic, ...]
    statuses: tuple[McpServerStatus, ...] = ()
