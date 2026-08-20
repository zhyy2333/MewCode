from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping
import uuid

from mewcode.agent import ToolPolicyDecision
from mewcode.permissions import PermissionPreflight, PermissionRuleSets
from mewcode.subagents import AgentDefinitionCatalog
from mewcode.tools import Tool, ToolRegistry, ToolResult, ToolSafety, ValidatedToolCall

from .approvals import TeamApprovalService
from .models import FrozenRoleSnapshot, TeamActor, TeamPermissionError, TeamValidationError

HARD_FORBIDDEN_MEMBER_TOOLS = frozenset(
    {"agent", "load_skill", "skill", "team", "team_member"}
)
MEMBER_COLLABORATION_TOOLS = frozenset({"team_task", "team_message"})


class FrozenRoleFactory:
    def __init__(
        self,
        catalog: AgentDefinitionCatalog,
        *,
        profile_names: Iterable[str],
        permission_rules: PermissionRuleSets = PermissionRuleSets(),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._catalog = catalog
        self._profiles = frozenset(profile_names)
        self._permission_rules = permission_rules
        self._now = now
        self._new_id = new_id

    def build(
        self,
        role_name: str,
        *,
        current_profile_name: str,
    ) -> FrozenRoleSnapshot:
        definition = self._catalog.get(role_name)
        if definition is None:
            raise TeamValidationError(f"Unknown member role '{role_name}'.")
        profile_name = (
            current_profile_name if definition.model == "inherit" else definition.model
        )
        if profile_name == "inherit" or profile_name not in self._profiles:
            raise TeamValidationError("Member role profile could not be resolved.")
        fields = {
            "role_name": definition.name,
            "description": definition.description,
            "system_prompt": definition.system_prompt,
            "profile_name": profile_name,
            "max_turns": definition.max_turns,
            "permission_mode": definition.permission_mode.value,
            "allowed_tool_names": list(definition.tools),
            "denied_tool_names": list(definition.disallowed_tools),
            "source": str(definition.source.path),
        }
        fingerprint = hashlib.sha256(
            json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return FrozenRoleSnapshot(
            self._new_id(),
            definition.name,
            fingerprint,
            definition.description,
            definition.system_prompt,
            profile_name,
            definition.max_turns,
            definition.permission_mode,
            tuple(definition.tools),
            tuple(definition.disallowed_tools),
            self._permission_rules,
            self._now(),
        )


@dataclass(frozen=True)
class TeamMemberToolPolicy:
    executable_names: frozenset[str]
    denial_reasons: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable_names", frozenset(self.executable_names))
        object.__setattr__(self, "denial_reasons", MappingProxyType(dict(self.denial_reasons)))

    def evaluate(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> ToolPolicyDecision:
        del preflight
        if call.tool.name in self.executable_names:
            return ToolPolicyDecision(True)
        return ToolPolicyDecision(
            False,
            self.denial_reasons.get(
                call.tool.name,
                "This tool is not available in the frozen team-member scope.",
            )[:512],
        )


@dataclass(frozen=True)
class MemberToolScope:
    registry: ToolRegistry
    policy: TeamMemberToolPolicy


class ApprovalGuardedTool:
    def __init__(
        self,
        tool: Tool,
        approvals: TeamApprovalService,
        actor: TeamActor,
        task_id: Callable[[], str | None],
    ) -> None:
        if tool.safety is not ToolSafety.SIDE_EFFECT:
            raise ValueError("Only side-effect tools need approval guards.")
        self._tool = tool
        self._approvals = approvals
        self._actor = actor
        self._task_id = task_id
        self.name = tool.name
        self.description = tool.description
        self.parameters_schema = tool.parameters_schema
        self.safety = tool.safety
        self.permission_spec = tool.permission_spec

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        task_id = self._task_id()
        if task_id is None:
            return ToolResult(
                False,
                self.name,
                "",
                "A current task and approved plan are required for side effects.",
                {"permission_denied": True, "approval_required": True},
            )
        try:
            async with self._approvals.side_effect_permit(self._actor, task_id):
                return await self._tool.execute(arguments)
        except TeamPermissionError as exc:
            return ToolResult(
                False,
                self.name,
                "",
                str(exc),
                {"permission_denied": True, "approval_required": True},
            )


def build_member_tool_scope(
    base_registry: ToolRegistry,
    role: FrozenRoleSnapshot,
    *,
    collaboration_registry: ToolRegistry | None = None,
    globally_disabled_names: Iterable[str] = (),
    workspace_allowed_names: Iterable[str] | None = None,
    allowed_safety: Iterable[ToolSafety] = (ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT),
    approvals: TeamApprovalService | None = None,
    actor: TeamActor | None = None,
    task_id: Callable[[], str | None] = lambda: None,
) -> MemberToolScope:
    disabled = frozenset(globally_disabled_names)
    workspace = (
        frozenset(base_registry.names)
        if workspace_allowed_names is None
        else frozenset(workspace_allowed_names)
    )
    safety = frozenset(allowed_safety)
    allowed = (
        frozenset(role.allowed_tool_names)
        .intersection(base_registry.names, workspace)
        .difference(role.denied_tool_names, disabled, HARD_FORBIDDEN_MEMBER_TOOLS)
    )
    tools: list[Tool] = []
    for name in base_registry.names:
        tool = base_registry.get(name)
        if tool is None or name not in allowed or tool.safety not in safety:
            continue
        if tool.safety is ToolSafety.SIDE_EFFECT and approvals is not None:
            if actor is None:
                raise ValueError("Approval-guarded scope requires a member actor.")
            tool = ApprovalGuardedTool(tool, approvals, actor, task_id)
        tools.append(tool)
    if collaboration_registry is not None:
        for tool in collaboration_registry.list():
            if tool.name in MEMBER_COLLABORATION_TOOLS:
                tools.append(tool)
    registry = ToolRegistry(tools)
    executable = frozenset(registry.names)
    return MemberToolScope(
        registry,
        TeamMemberToolPolicy(
            executable,
            {
                name: "The frozen member role, workspace, or global policy denies this tool."
                for name in set(base_registry.names).union(
                    collaboration_registry.names if collaboration_registry is not None else ()
                )
                if name not in executable
            },
        ),
    )
