from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from .models import (
    McpCallResult,
    McpDiagnostic,
    McpError,
    McpManagerStartResult,
    McpPhase,
    McpServerConfig,
    McpServerStartState,
    McpServerStatus,
    McpTimeouts,
    McpToolDescriptor,
    McpUnavailableError,
)
from .naming import public_tool_name
from .session import McpClientSession
from .transport import McpTransportFactory


class McpManager:
    def __init__(
        self,
        transport_factory: McpTransportFactory,
        timeouts: McpTimeouts | None = None,
    ) -> None:
        self._factory = transport_factory
        self._timeouts = timeouts or McpTimeouts()
        self._sessions: dict[str, McpClientSession] = {}
        self._closed = False

    async def start(
        self,
        configs: tuple[McpServerConfig, ...],
        reserved_tool_names: set[str],
    ) -> McpManagerStartResult:
        outcomes = await asyncio.gather(
            *(self._start_one(config) for config in configs),
            return_exceptions=True,
        )
        diagnostics: list[McpDiagnostic] = []
        descriptors: list[McpToolDescriptor] = []
        statuses: list[McpServerStatus] = []
        accepted = set(reserved_tool_names)
        for config, outcome in zip(configs, outcomes, strict=True):
            session = self._sessions.get(config.name)
            if isinstance(outcome, BaseException):
                message = (
                    outcome.safe_message
                    if isinstance(outcome, McpError)
                    else "MCP server startup failed."
                )
                diagnostics.append(
                    McpDiagnostic(config.name, McpPhase.STARTUP, message)
                )
                statuses.append(
                    McpServerStatus(
                        config.name, McpServerStartState.FAILED, (), message
                    )
                )
                if session is not None:
                    diagnostics.extend(await session.close())
                continue
            raw_tools, session_diagnostics = outcome
            diagnostics.extend(session_diagnostics)
            counts = Counter(tool["name"] for tool in raw_tools)
            server_descriptors: list[McpToolDescriptor] = []
            for raw in raw_tools:
                original = raw["name"]
                if counts[original] > 1:
                    diagnostics.append(
                        McpDiagnostic(
                            config.name,
                            McpPhase.STARTUP,
                            f"duplicate tool '{original}' was skipped",
                        )
                    )
                    continue
                public = public_tool_name(config.name, original)
                if public in accepted:
                    diagnostics.append(
                        McpDiagnostic(
                            config.name,
                            McpPhase.STARTUP,
                            f"tool name collision for '{public}' was skipped",
                        )
                    )
                    continue
                accepted.add(public)
                server_descriptors.append(
                    McpToolDescriptor(
                        config.name,
                        original,
                        public,
                        raw.get("description", ""),
                        raw["inputSchema"],
                    )
                )
            if not server_descriptors and session is not None:
                diagnostics.extend(await session.close())
                message = "server exposed no valid tools"
                diagnostics.append(
                    McpDiagnostic(
                        config.name,
                        McpPhase.STARTUP,
                        message,
                    )
                )
                statuses.append(
                    McpServerStatus(
                        config.name, McpServerStartState.FAILED, (), message
                    )
                )
                continue
            descriptors.extend(server_descriptors)
            statuses.append(
                McpServerStatus(
                    config.name,
                    McpServerStartState.READY,
                    tuple(item.public_name for item in server_descriptors),
                )
            )
        return McpManagerStartResult(
            tuple(sorted(descriptors, key=lambda item: item.public_name)),
            tuple(diagnostics),
            tuple(statuses),
        )

    async def call_tool(
        self, server_name: str, original_name: str, arguments: dict[str, Any]
    ) -> McpCallResult:
        session = self._sessions.get(server_name)
        if session is None:
            raise McpUnavailableError(
                server_name,
                McpPhase.CALL,
                "MCP server is unavailable.",
                session_fatal=True,
            )
        return await session.call_tool(original_name, arguments)

    async def close(self) -> tuple[McpDiagnostic, ...]:
        if self._closed:
            return ()
        self._closed = True
        results = await asyncio.gather(
            *(session.close() for session in self._sessions.values()),
            return_exceptions=True,
        )
        diagnostics: list[McpDiagnostic] = []
        for name, result in zip(self._sessions, results, strict=True):
            if isinstance(result, BaseException):
                diagnostics.append(
                    McpDiagnostic(name, McpPhase.SHUTDOWN, "MCP session close failed")
                )
            else:
                diagnostics.extend(result)
        return tuple(diagnostics)

    async def _start_one(
        self, config: McpServerConfig
    ) -> tuple[tuple[dict[str, Any], ...], tuple[McpDiagnostic, ...]]:
        transport = self._factory.create(config)
        session = McpClientSession(config.name, transport, self._timeouts)
        self._sessions[config.name] = session
        tools = await session.start()
        return tools, session.diagnostics
