from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from mewcode.agent import ToolPolicyDecision
from mewcode.permissions import PermissionPreflight
from mewcode.tools import ToolRegistry, ToolSafety, ValidatedToolCall

from .models import AgentDefinition


DEFAULT_GLOBALLY_FORBIDDEN_TOOLS = frozenset({"agent", "load_skill"})


@dataclass(frozen=True)
class FrozenSubagentToolPolicy:
    executable_names: frozenset[str]
    denial_reasons: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable_names", frozenset(self.executable_names))
        object.__setattr__(
            self,
            "denial_reasons",
            MappingProxyType(dict(self.denial_reasons)),
        )

    def evaluate(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> ToolPolicyDecision:
        name = call.tool.name
        if name in self.executable_names:
            return ToolPolicyDecision(True)
        return ToolPolicyDecision(
            False,
            self.denial_reasons.get(
                name,
                "This tool is not executable in the frozen subagent task scope.",
            )[:512],
        )


@dataclass(frozen=True)
class DefinedToolScope:
    registry: ToolRegistry
    policy: FrozenSubagentToolPolicy


def build_defined_tool_scope(
    base_registry: ToolRegistry,
    definition: AgentDefinition,
    *,
    parent_mode_names: Iterable[str],
    background_capable_names: Iterable[str],
    allowed_safety: Iterable[ToolSafety],
    globally_forbidden_names: Iterable[str] = DEFAULT_GLOBALLY_FORBIDDEN_TOOLS,
) -> DefinedToolScope:
    parent = frozenset(parent_mode_names)
    background = frozenset(background_capable_names)
    safety = frozenset(allowed_safety)
    forbidden = frozenset(globally_forbidden_names)
    role_allowed = frozenset(definition.tools)
    role_denied = frozenset(definition.disallowed_tools)
    executable = (
        parent.intersection(role_allowed, background)
        .difference(role_denied)
        .difference(forbidden)
    )
    executable = frozenset(
        name
        for name in executable
        if (tool := base_registry.get(name)) is not None and tool.safety in safety
    )
    registry = base_registry.select_names(executable)
    reasons = {
        name: "The defined subagent role does not allow this tool."
        for name in base_registry.names
        if name not in executable
    }
    return DefinedToolScope(
        registry,
        FrozenSubagentToolPolicy(executable, reasons),
    )


def build_fork_tool_policy(
    parent_registry: ToolRegistry | None,
    *,
    background_capable_names: Iterable[str],
    parent_mode_names: Iterable[str],
    allowed_safety: Iterable[ToolSafety],
    globally_forbidden_names: Iterable[str] = DEFAULT_GLOBALLY_FORBIDDEN_TOOLS,
) -> FrozenSubagentToolPolicy:
    if parent_registry is None:
        return FrozenSubagentToolPolicy(frozenset(), {})
    background = frozenset(background_capable_names)
    parent_mode = frozenset(parent_mode_names)
    safety = frozenset(allowed_safety)
    forbidden = frozenset(globally_forbidden_names)
    executable: set[str] = set()
    reasons: dict[str, str] = {}
    for tool in parent_registry.list():
        name = tool.name
        if name in forbidden:
            reasons[name] = "Control and model-delegation tools are forbidden in subagents."
        elif name not in background:
            reasons[name] = "This tool was not present in the frozen background-capable set."
        elif name not in parent_mode or tool.safety not in safety:
            reasons[name] = "The parent mode does not permit this tool in a subagent."
        else:
            executable.add(name)
    return FrozenSubagentToolPolicy(frozenset(executable), reasons)
