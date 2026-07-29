from __future__ import annotations

import re
import subprocess
from typing import Any

from .base import DEFAULT_TOOL_CONTENT_LIMIT, ToolResult, truncate_text
from .workspace import Workspace

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
MAX_COMMAND_TIMEOUT_SECONDS = 120

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

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments["command"]
        if not command.strip():
            return ToolResult(ok=False, tool_name=self.name, content="", error="command must not be empty.")

        timeout = arguments.get("timeout_seconds", self._default_timeout_seconds)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                content="",
                error="timeout_seconds must be a positive integer.",
            )
        if timeout > self._max_timeout_seconds:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                content="",
                error=f"timeout_seconds must not exceed {self._max_timeout_seconds}.",
            )

        if _is_dangerous(command):
            return ToolResult(
                ok=False,
                tool_name=self.name,
                content="",
                error="Command rejected by safety policy.",
                metadata={"blocked": True},
            )

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self._workspace.root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_output(exc.stdout)
            stderr = _coerce_output(exc.stderr)
            return ToolResult(
                ok=False,
                tool_name=self.name,
                content="Command timed out.",
                error=f"Command timed out after {timeout} seconds.",
                metadata={
                    "timed_out": True,
                    "timeout_seconds": timeout,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )
        except OSError as exc:
            return ToolResult(ok=False, tool_name=self.name, content="", error=str(exc))

        stdout, stdout_truncated = truncate_text(completed.stdout, self._content_limit)
        stderr, stderr_truncated = truncate_text(completed.stderr, self._content_limit)
        content = _format_command_content(completed.returncode, stdout, stderr)
        return ToolResult(
            ok=completed.returncode == 0,
            tool_name=self.name,
            content=content,
            error=None if completed.returncode == 0 else f"Command exited with {completed.returncode}.",
            metadata={
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
                "truncated": stdout_truncated or stderr_truncated,
                "cwd": str(self._workspace.root),
            },
        )


def _is_dangerous(command: str) -> bool:
    normalized = command.lower()
    return any(re.search(pattern, normalized) for pattern in DANGEROUS_COMMAND_PATTERNS)


def _coerce_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _format_command_content(exit_code: int, stdout: str, stderr: str) -> str:
    parts = [f"exit_code: {exit_code}"]
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    return "\n".join(parts)
