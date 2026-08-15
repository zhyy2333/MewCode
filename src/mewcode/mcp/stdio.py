from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .models import (
    MCP_MAX_MESSAGE_BYTES,
    McpDiagnostic,
    McpPhase,
    McpTransportError,
    StdioServerConfig,
)
from .transport import FailureHandler, MessageHandler


class StdioTransport:
    def __init__(
        self,
        config: StdioServerConfig,
        workspace_root: Path,
        *,
        shutdown_timeout: float = 5.0,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self.server_name = config.name
        self._config = config
        self._workspace_root = workspace_root
        self._shutdown_timeout = shutdown_timeout
        self._environment_overrides = dict(environment_overrides or {})
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._on_message: MessageHandler | None = None
        self._on_failure: FailureHandler | None = None
        self._closing = False
        self._closed = False

    async def start(
        self, on_message: MessageHandler, on_failure: FailureHandler
    ) -> None:
        self._on_message = on_message
        self._on_failure = on_failure
        environment = os.environ.copy()
        environment.update(self._environment_overrides)
        environment.update(dict(self._config.env_overrides))
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._config.command,
                *self._config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace_root,
                env=environment,
                limit=MCP_MAX_MESSAGE_BYTES + 1,
            )
        except (OSError, ValueError) as exc:
            raise McpTransportError(
                self.server_name,
                McpPhase.STARTUP,
                "MCP stdio process could not be started.",
                session_fatal=True,
            ) from exc
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def send(self, message: dict[str, Any]) -> None:
        process = self._process
        if self._closed or process is None or process.stdin is None:
            raise self._error("MCP stdio transport is unavailable.")
        try:
            payload = json.dumps(
                message, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise self._error("MCP message is not JSON serializable.") from exc
        if len(payload) > MCP_MAX_MESSAGE_BYTES:
            raise self._error("MCP message exceeds the size limit.")
        try:
            async with self._write_lock:
                process.stdin.write(payload + b"\n")
                await process.stdin.drain()
        except (BrokenPipeError, ConnectionError, OSError) as exc:
            raise self._error("MCP stdio pipe is closed.") from exc

    def set_protocol_version(self, version: str) -> None:
        return None

    async def close(self) -> tuple[McpDiagnostic, ...]:
        if self._closed:
            return ()
        self._closing = True
        process = self._process
        diagnostics: list[McpDiagnostic] = []
        if process is not None:
            loop = asyncio.get_running_loop()
            started = loop.time()
            graceful_deadline = started + self._shutdown_timeout / 3
            terminate_deadline = started + self._shutdown_timeout * 2 / 3
            final_deadline = started + self._shutdown_timeout
            if process.stdin is not None and not process.stdin.is_closing():
                process.stdin.close()
                with suppress(Exception):
                    await asyncio.wait_for(
                        process.stdin.wait_closed(),
                        max(0.01, graceful_deadline - loop.time()),
                    )
            if not await self._wait_process(graceful_deadline):
                with suppress(ProcessLookupError, OSError):
                    process.terminate()
                if not await self._wait_process(terminate_deadline):
                    with suppress(ProcessLookupError, OSError):
                        process.kill()
                    if not await self._wait_process(final_deadline):
                        diagnostics.append(
                            McpDiagnostic(
                                self.server_name,
                                McpPhase.SHUTDOWN,
                                "stdio process did not exit before shutdown deadline",
                            )
                        )
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                with suppress(asyncio.CancelledError, Exception):
                    await task
        self._closed = True
        return tuple(diagnostics)

    async def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    if not self._closing:
                        await self._report_failure("MCP stdio server closed stdout.")
                    return
                if len(line) > MCP_MAX_MESSAGE_BYTES + 1 or not line.endswith(b"\n"):
                    await self._report_failure("MCP stdio message exceeds the size limit.")
                    return
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    await self._report_failure("MCP stdio server sent invalid JSON.")
                    return
                if not isinstance(message, dict):
                    await self._report_failure("MCP stdio message must be a JSON object.")
                    return
                assert self._on_message is not None
                await self._on_message(message)
        except (ValueError, asyncio.LimitOverrunError):
            await self._report_failure("MCP stdio message exceeds the size limit.")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._closing:
                await self._report_failure("MCP stdio reader failed.")

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            while await self._process.stderr.read(64 * 1024):
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _report_failure(self, message: str) -> None:
        if self._on_failure is not None:
            await self._on_failure(self._error(message))

    async def _wait_process(self, deadline: float) -> bool:
        assert self._process is not None
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return self._process.returncode is not None
        try:
            await asyncio.wait_for(self._process.wait(), remaining)
            return True
        except TimeoutError:
            return False

    def _error(self, message: str) -> McpTransportError:
        return McpTransportError(
            self.server_name,
            McpPhase.CALL,
            message,
            session_fatal=True,
        )
