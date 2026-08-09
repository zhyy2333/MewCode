from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mewcode.permissions import (
    PermissionOutcome,
    PermissionSource,
    PermissionTarget,
    PermissionTargetBuilder,
)
from mewcode.tools import (
    PermissionTargetKind,
    ToolCallRequest,
    ToolPermissionSpec,
    ValidatedToolCall,
    Workspace,
)


def call(
    name: str,
    argument: str,
    value: str | None,
    kind: PermissionTargetKind,
    default: str | None = None,
) -> ValidatedToolCall:
    arguments = {} if value is None else {argument: value}
    tool = SimpleNamespace(
        name=name, permission_spec=ToolPermissionSpec(argument, kind, default)
    )
    request = ToolCallRequest("call", name, arguments, "{}")
    return ValidatedToolCall(request, tool)


def test_command_target_is_trimmed_and_blacklist_is_hard_denial(tmp_path: Path) -> None:
    builder = PermissionTargetBuilder(Workspace(tmp_path))
    safe = builder.build(
        call("run_command", "command", "  git status  ", PermissionTargetKind.COMMAND)
    )
    assert safe == PermissionTarget(
        "run_command", "git status", PermissionTargetKind.COMMAND
    )
    denied = builder.build(
        call("run_command", "command", "rm -rf /", PermissionTargetKind.COMMAND)
    )
    assert denied.outcome == PermissionOutcome.DENY
    assert denied.source == PermissionSource.BLACKLIST
    assert denied.target is None


def test_path_target_is_relative_and_ignores_unrelated_arguments(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    request = call("write_file", "path", "src/a.py", PermissionTargetKind.PATH)
    request.request.arguments["content"] = "secret"
    built = PermissionTargetBuilder(workspace).build(request)
    assert built == PermissionTarget("write_file", "src/a.py", PermissionTargetKind.PATH)


@pytest.mark.parametrize("value", ["../outside", "C:/Windows/system.ini"])
def test_path_target_rejects_workspace_escape(tmp_path: Path, value: str) -> None:
    denied = PermissionTargetBuilder(Workspace(tmp_path)).build(
        call("read_file", "path", value, PermissionTargetKind.PATH)
    )
    assert denied.outcome == PermissionOutcome.DENY
    assert denied.source == PermissionSource.SANDBOX


def test_path_glob_normalizes_and_rejects_traversal(tmp_path: Path) -> None:
    builder = PermissionTargetBuilder(Workspace(tmp_path))
    valid = builder.build(
        call("find_files", "pattern", r"src\**\*.py", PermissionTargetKind.PATH_GLOB)
    )
    assert valid.value == "src/**/*.py"
    denied = builder.build(
        call("find_files", "pattern", "../**", PermissionTargetKind.PATH_GLOB)
    )
    assert denied.source == PermissionSource.SANDBOX


def test_default_target_and_missing_declaration(tmp_path: Path) -> None:
    builder = PermissionTargetBuilder(Workspace(tmp_path))
    defaulted = builder.build(
        call("search_code", "path", None, PermissionTargetKind.PATH, ".")
    )
    assert defaulted.value == "."
    tool = SimpleNamespace(name="custom")
    request = ToolCallRequest("call", "custom", {}, "{}")
    denied = builder.build(ValidatedToolCall(request, tool))
    assert denied.source == PermissionSource.CONFIG_ERROR
