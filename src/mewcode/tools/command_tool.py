from __future__ import annotations

from typing import Any

from mewcode.processes import ProcessRequest, run_shell

from .base import (
    DEFAULT_TOOL_CONTENT_LIMIT,
    PermissionTargetKind,
    ToolPermissionSpec,
    ToolResult,
    ToolSafety,
    truncate_text,
)
from .safety import check_dangerous_command
from .workspace import Workspace

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
MAX_COMMAND_TIMEOUT_SECONDS = 120

class RunCommandTool:
    name = "run_command"
    description = "Run a command in the current workspace with timeout and safety checks. Use only when the dedicated read, find, search, write, or edit tools cannot complete the operation."
    safety = ToolSafety.SIDE_EFFECT
    permission_spec = ToolPermissionSpec("command", PermissionTargetKind.COMMAND)
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
        dangerous = check_dangerous_command(command)
        if dangerous is not None:
            return ToolResult(
                False,
                self.name,
                "",
                "Command rejected by safety policy.",
                {
                    "blocked": True,
                    "category": dangerous.category,
                },
            )

        try:
            result = await run_shell(
                ProcessRequest(
                    command=command,
                    cwd=self._workspace.root,
                    timeout_seconds=timeout,
                    stdout_limit=max(self._content_limit * 4, 1024 * 1024),
                    stderr_limit=max(self._content_limit * 4, 1024 * 1024),
                )
            )
        except OSError as exc:
            return ToolResult(False, self.name, "", str(exc))
        if result.timed_out:
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
        stdout, stdout_truncated = truncate_text(
            _decode_output(result.stdout), self._content_limit
        )
        stderr, stderr_truncated = truncate_text(
            _decode_output(result.stderr), self._content_limit
        )
        return_code = result.exit_code
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
                "truncated": stdout_truncated or stderr_truncated or result.output_exceeded,
                "cwd": str(self._workspace.root),
            },
        )
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
