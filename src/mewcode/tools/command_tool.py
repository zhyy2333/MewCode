from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
from typing import Any

from .base import DEFAULT_TOOL_CONTENT_LIMIT, ToolResult, ToolSafety, truncate_text
from .workspace import Workspace

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
MAX_COMMAND_TIMEOUT_SECONDS = 120
PROCESS_STOP_TIMEOUT_SECONDS = 1.0

DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+(-[^\s]*[rf][^\s]*|-r|-f)\s+[/\\]?",
    r"\bdel\s+/(s|q)\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bchmod\s+(-[^\s]*R[^\s]*|777)\b",
    r"\bchown\s+-R\b",
    r"\bmkfs\b",
    r"\bdiskpart\b",
]


class RunCommandTool:
    name = "run_command"
    description = "Run a command in the current workspace with timeout and safety checks."
    safety = ToolSafety.SIDE_EFFECT
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["command"],
    }

    def __init__(
        self,
        workspace: Workspace,
        default_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        max_timeout_seconds: int = MAX_COMMAND_TIMEOUT_SECONDS,
        content_limit: int = DEFAULT_TOOL_CONTENT_LIMIT,
    ) -> None:
        self._workspace = workspace
        self._default_timeout_seconds = default_timeout_seconds
        self._max_timeout_seconds = max_timeout_seconds
        self._content_limit = content_limit

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments["command"]
        if not command.strip():
            return ToolResult(False, self.name, "", "command must not be empty.")

        timeout = arguments.get("timeout_seconds", self._default_timeout_seconds)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            return ToolResult(
                False, self.name, "", "timeout_seconds must be a positive integer."
            )
        if timeout > self._max_timeout_seconds:
            return ToolResult(
                False,
                self.name,
                "",
                f"timeout_seconds must not exceed {self._max_timeout_seconds}.",
            )
        if _is_dangerous(command):
            return ToolResult(
                False,
                self.name,
                "",
                "Command rejected by safety policy.",
                {"blocked": True},
            )

        try:
            process_options: dict[str, Any]
            if os.name == "nt":
                process_options = {
                    "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                }
            else:
                process_options = {"start_new_session": True}
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self._workspace.root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **process_options,
            )
        except OSError as exc:
            return ToolResult(False, self.name, "", str(exc))

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            await _stop_process(process)
            return ToolResult(
                ok=False,
                tool_name=self.name,
                content="Command timed out.",
                error=f"Command timed out after {timeout} seconds.",
                metadata={
                    "timed_out": True,
                    "timeout_seconds": timeout,
                    "stdout": "",
                    "stderr": "",
                },
            )
        except asyncio.CancelledError:
            await _stop_process(process)
            raise

        await process.wait()
        _close_process_transport(process)
        await asyncio.sleep(0)
        stdout, stdout_truncated = truncate_text(
            _decode_output(stdout_bytes), self._content_limit
        )
        stderr, stderr_truncated = truncate_text(
            _decode_output(stderr_bytes), self._content_limit
        )
        return_code = process.returncode if process.returncode is not None else -1
        content = _format_command_content(return_code, stdout, stderr)
        return ToolResult(
            ok=return_code == 0,
            tool_name=self.name,
            content=content,
            error=None if return_code == 0 else f"Command exited with {return_code}.",
            metadata={
                "exit_code": return_code,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
                "truncated": stdout_truncated or stderr_truncated,
                "cwd": str(self._workspace.root),
            },
        )


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    try:
        if process.returncode is None:
            if os.name == "nt":
                await _stop_windows_process_tree(process.pid)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=PROCESS_STOP_TIMEOUT_SECONDS
                )
            except TimeoutError:
                if os.name == "nt":
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                await process.wait()
    finally:
        _close_process_transport(process)
        await asyncio.sleep(0)


async def _stop_windows_process_tree(pid: int) -> None:
    try:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(
            killer.communicate(), timeout=PROCESS_STOP_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError):
        pass


def _close_process_transport(process: asyncio.subprocess.Process) -> None:
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()


def _is_dangerous(command: str) -> bool:
    normalized = command.lower()
    return any(re.search(pattern, normalized) for pattern in DANGEROUS_COMMAND_PATTERNS)


def _decode_output(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace")


def _format_command_content(exit_code: int, stdout: str, stderr: str) -> str:
    parts = [f"exit_code: {exit_code}"]
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    return "\n".join(parts)
