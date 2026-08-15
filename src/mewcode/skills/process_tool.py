from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from mewcode.tools import (
    DEFAULT_TOOL_CONTENT_LIMIT,
    PermissionTargetKind,
    ToolPermissionSpec,
    ToolResult,
    truncate_text,
)

from .materialization import MaterializedSkill
from .models import (
    MAX_TOOL_STDERR_BYTES,
    MAX_TOOL_STDIN_BYTES,
    MAX_TOOL_STDOUT_BYTES,
    SkillDefinitionError,
    SkillToolDeclaration,
)
from .paths import ensure_package_path


class SkillProcessTool:
    def __init__(
        self,
        declaration: SkillToolDeclaration,
        package: MaterializedSkill,
        workspace_root: Path,
        *,
        api_key_environment_names: Iterable[str] = (),
        environment_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self.name = declaration.public_name
        self.description = declaration.description
        self.parameters_schema = declaration.parameters
        self.safety = declaration.safety
        self.permission_spec = ToolPermissionSpec(
            None, PermissionTargetKind.TOOL, default=self.name
        )
        self._validator = Draft202012Validator(declaration.parameters)
        self._command = _resolve_command(declaration.command, package.root)
        self._timeout = declaration.timeout_seconds
        self._package = package.root
        self._workspace = workspace_root.resolve()
        self._key_names = frozenset(api_key_environment_names)
        self._environment_overrides = dict(environment_overrides or {})
        self._last_stderr = ""

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        errors = sorted(self._validator.iter_errors(arguments), key=lambda item: list(item.path))
        if errors:
            return self._failure(f"Invalid tool arguments: {errors[0].message}")
        encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_TOOL_STDIN_BYTES:
            return self._failure("Tool input exceeds the 1 MiB limit.")
        environment = dict(os.environ)
        for name in self._key_names:
            environment.pop(name, None)
        environment.update(self._environment_overrides)
        environment["MEWCODE_SKILL_DIR"] = str(self._package)
        environment["MEWCODE_WORKSPACE_ROOT"] = str(self._workspace)
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
                env=environment,
            )
        except OSError:
            return self._failure("Skill tool process could not be started.")
        try:
            stdout, stderr = await asyncio.wait_for(
                _communicate_bounded(process, encoded), timeout=self._timeout
            )
        except TimeoutError:
            await _terminate(process)
            return self._failure(f"Skill tool timed out after {self._timeout} seconds.")
        except _OutputLimitError as exc:
            await _terminate(process)
            return self._failure(str(exc))
        except asyncio.CancelledError:
            await _terminate(process)
            raise
        self._last_stderr = stderr[:MAX_TOOL_STDERR_BYTES].decode("utf-8", "replace")
        if process.returncode != 0:
            return self._failure(f"Skill tool exited with code {process.returncode}.")
        try:
            result = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._failure("Skill tool returned invalid JSON.")
        error = _validate_result(result)
        if error:
            return self._failure(error)
        content, truncated = truncate_text(result["content"], DEFAULT_TOOL_CONTENT_LIMIT)
        metadata = result.get("metadata", {})
        if truncated:
            metadata = {**metadata, "truncated": True}
        return ToolResult(
            bool(result["ok"]),
            self.name,
            content,
            result.get("error"),
            metadata,
        )

    def _failure(self, message: str) -> ToolResult:
        return ToolResult(False, self.name, "", message)

    def rebind_workspace(
        self,
        workspace_root: Path,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> "SkillProcessTool":
        clone = object.__new__(SkillProcessTool)
        clone.name = self.name
        clone.description = self.description
        clone.parameters_schema = self.parameters_schema
        clone.safety = self.safety
        clone.permission_spec = self.permission_spec
        clone._validator = self._validator
        clone._command = self._command
        clone._timeout = self._timeout
        clone._package = self._package
        clone._workspace = workspace_root.resolve()
        clone._key_names = self._key_names
        clone._environment_overrides = dict(environment_overrides or {})
        clone._last_stderr = ""
        return clone


def create_skill_tools(
    declarations: Iterable[SkillToolDeclaration],
    package: MaterializedSkill | None,
    workspace_root: Path,
    *,
    api_key_environment_names: Iterable[str] = (),
) -> tuple[SkillProcessTool, ...]:
    declarations = tuple(declarations)
    if declarations and package is None:
        raise SkillDefinitionError("Package tools require a materialized Skill directory.")
    if package is None:
        return ()
    return tuple(
        SkillProcessTool(
            declaration,
            package,
            workspace_root,
            api_key_environment_names=api_key_environment_names,
        )
        for declaration in declarations
    )


def _resolve_command(command: tuple[str, ...], package: Path) -> tuple[str, ...]:
    resolved: list[str] = []
    for index, argument in enumerate(command):
        path = Path(argument)
        if index == 0:
            if path.is_absolute():
                resolved.append(str(path))
            elif argument.startswith(".") or "/" in argument or "\\" in argument:
                resolved.append(str(ensure_package_path(package, argument)))
            else:
                resolved.append(argument)
            continue
        package_candidate = package / argument
        if (
            not argument.startswith("-")
            and (
                argument.startswith(".")
                or "/" in argument
                or "\\" in argument
                or package_candidate.is_file()
            )
        ):
            resolved.append(str(ensure_package_path(package, argument)))
        else:
            resolved.append(argument)
    return tuple(resolved)


def _validate_result(result: Any) -> str | None:
    if not isinstance(result, dict):
        return "Skill tool result must be a JSON object."
    allowed = {"ok", "content", "error", "metadata"}
    if set(result) - allowed or "ok" not in result or "content" not in result:
        return "Skill tool result has invalid fields."
    if not isinstance(result["ok"], bool) or not isinstance(result["content"], str):
        return "Skill tool result fields 'ok' and 'content' have invalid types."
    if "error" in result and result["error"] is not None and not isinstance(result["error"], str):
        return "Skill tool result field 'error' must be a string."
    if "metadata" in result and not isinstance(result["metadata"], dict):
        return "Skill tool result field 'metadata' must be an object."
    return None


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.kill()
    try:
        await process.wait()
    except ProcessLookupError:
        pass


class _OutputLimitError(RuntimeError):
    pass


async def _communicate_bounded(
    process: asyncio.subprocess.Process, encoded: bytes
) -> tuple[bytes, bytes]:
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    async def write_input() -> None:
        process.stdin.write(encoded)
        await process.stdin.drain()
        process.stdin.close()

    async def read_stream(
        stream: asyncio.StreamReader, limit: int, label: str
    ) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await stream.read(min(65_536, limit + 1 - size))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise _OutputLimitError(f"Skill tool {label} exceeds its output limit.")

    write_task = asyncio.create_task(write_input())
    stdout_task = asyncio.create_task(
        read_stream(process.stdout, MAX_TOOL_STDOUT_BYTES, "stdout")
    )
    stderr_task = asyncio.create_task(
        read_stream(process.stderr, MAX_TOOL_STDERR_BYTES, "stderr")
    )
    try:
        await write_task
        stdout, stderr, _returncode = await asyncio.gather(
            stdout_task, stderr_task, process.wait()
        )
        return stdout, stderr
    except BaseException:
        for task in (write_task, stdout_task, stderr_task):
            task.cancel()
        await asyncio.gather(write_task, stdout_task, stderr_task, return_exceptions=True)
        raise
