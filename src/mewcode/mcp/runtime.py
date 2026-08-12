from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from .manager import McpManager
from .models import (
    McpCallResult,
    McpDiagnostic,
    McpError,
    McpPhase,
    McpServerConfig,
    McpServerStatus,
    McpTimeouts,
    McpTransportError,
)
from .tool import McpTool
from .transport import DefaultMcpTransportFactory, McpTransportFactory


@dataclass(frozen=True)
class McpRuntimeStartResult:
    tools: tuple[McpTool, ...]
    diagnostics: tuple[McpDiagnostic, ...]
    statuses: tuple[McpServerStatus, ...] = ()


class McpRuntime:
    def __init__(
        self,
        workspace_root: Path,
        *,
        timeouts: McpTimeouts | None = None,
        transport_factory: McpTransportFactory | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._timeouts = timeouts or McpTimeouts()
        self._transport_factory = transport_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._manager: McpManager | None = None
        self._started = False
        self._closed = False

    def start(
        self,
        configs: tuple[McpServerConfig, ...],
        reserved_tool_names: set[str],
    ) -> McpRuntimeStartResult:
        if self._started:
            raise RuntimeError("MCP runtime can only be started once.")
        self._started = True
        if not configs:
            return McpRuntimeStartResult((), (), ())
        self._thread = threading.Thread(
            target=self._run_loop,
            name="mewcode-mcp",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=self._timeouts.startup_seconds):
            self._closed = True
            raise McpTransportError(
                "runtime", McpPhase.STARTUP, "MCP runtime loop did not start."
            )
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(
            self._start_manager(configs, reserved_tool_names), self._loop
        )
        try:
            result = future.result(
                timeout=self._timeouts.startup_seconds * max(1, len(configs)) + 1
            )
        except Exception:
            self.close()
            raise
        return McpRuntimeStartResult(
            tuple(McpTool(descriptor, self) for descriptor in result.descriptors),
            result.diagnostics,
            result.statuses,
        )

    async def call_tool(
        self, server_name: str, original_name: str, arguments: dict[str, Any]
    ) -> McpCallResult:
        if self._loop is None or self._manager is None or self._closed:
            raise McpTransportError(
                server_name,
                McpPhase.CALL,
                "MCP runtime is unavailable.",
                session_fatal=True,
            )
        concurrent_future: Future[McpCallResult] = asyncio.run_coroutine_threadsafe(
            self._manager.call_tool(server_name, original_name, arguments),
            self._loop,
        )
        try:
            return await asyncio.wrap_future(concurrent_future)
        except asyncio.CancelledError:
            concurrent_future.cancel()
            raise

    def close(self) -> tuple[McpDiagnostic, ...]:
        if self._closed:
            return ()
        self._closed = True
        diagnostics: tuple[McpDiagnostic, ...] = ()
        if self._loop is not None and self._manager is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._manager.close(), self._loop)
            try:
                diagnostics = future.result(
                    timeout=self._timeouts.shutdown_seconds * max(1, len(self._manager._sessions)) + 1
                )
            except Exception:
                diagnostics = (
                    McpDiagnostic("runtime", McpPhase.SHUTDOWN, "MCP runtime close failed"),
                )
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=self._timeouts.shutdown_seconds + 1)
            if self._thread.is_alive():
                diagnostics += (
                    McpDiagnostic(
                        "runtime",
                        McpPhase.SHUTDOWN,
                        "MCP runtime thread did not stop before the deadline",
                    ),
                )
        return diagnostics

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _start_manager(self, configs, reserved_tool_names):
        factory = self._transport_factory or DefaultMcpTransportFactory(
            self._workspace_root, self._timeouts
        )
        self._manager = McpManager(factory, self._timeouts)
        return await self._manager.start(configs, reserved_tool_names)
