from __future__ import annotations

from mewcode.tools import (
    PermissionTargetKind,
    ValidatedToolCall,
    Workspace,
    WorkspaceError,
    check_dangerous_command,
)

from .models import (
    PermissionDecision,
    PermissionOutcome,
    PermissionSource,
    PermissionTarget,
)


class PermissionTargetBuilder:
    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def build(self, call: ValidatedToolCall) -> PermissionTarget | PermissionDecision:
        spec = getattr(call.tool, "permission_spec", None)
        if spec is None:
            return self._deny_config("Tool has no permission target declaration.")
        if spec.kind == PermissionTargetKind.TOOL:
            if spec.argument is not None:
                return self._deny_config(
                    "Static tool permission target must not read a call argument."
                )
            if not isinstance(spec.default, str) or not spec.default.strip():
                return self._deny_config("Tool permission target is missing or invalid.")
            return PermissionTarget(call.tool.name, spec.default.strip(), spec.kind)
        if spec.argument is None:
            return self._deny_config("Tool permission target argument is missing.")
        value = call.request.arguments.get(spec.argument, spec.default)
        if not isinstance(value, str) or not value.strip():
            return self._deny_config("Tool permission target is missing or invalid.")

        if spec.kind == PermissionTargetKind.COMMAND:
            command = value.strip()
            dangerous = check_dangerous_command(command)
            if dangerous is not None:
                return PermissionDecision(
                    outcome=PermissionOutcome.DENY,
                    target=None,
                    source=PermissionSource.BLACKLIST,
                    reason=f"Blocked dangerous command category: {dangerous.category}.",
                )
            return PermissionTarget(call.tool.name, command, spec.kind)

        try:
            if spec.kind == PermissionTargetKind.PATH:
                normalized = self._workspace.relative_path(
                    self._workspace.resolve_path(value)
                )
            elif spec.kind == PermissionTargetKind.PATH_GLOB:
                normalized = self._workspace.normalize_glob(value)
            else:
                return self._deny_config("Tool declares an unknown permission target kind.")
        except (OSError, ValueError, WorkspaceError) as exc:
            return PermissionDecision(
                outcome=PermissionOutcome.DENY,
                target=None,
                source=PermissionSource.SANDBOX,
                reason=f"Workspace sandbox rejected the target: {exc}",
            )
        return PermissionTarget(call.tool.name, normalized, spec.kind)

    @staticmethod
    def _deny_config(reason: str) -> PermissionDecision:
        return PermissionDecision(
            outcome=PermissionOutcome.DENY,
            target=None,
            source=PermissionSource.CONFIG_ERROR,
            reason=reason,
        )
