from __future__ import annotations

from pathlib import Path

from mewcode.permissions import PermissionMode
from mewcode.subagents import (
    AgentDefinition,
    AgentDefinitionLayer,
    AgentDefinitionSource,
    build_defined_tool_scope,
    build_fork_tool_policy,
)
from mewcode.tools import ToolRegistry, ToolSafety, ValidatedToolCall
from tests.fakes import ControlledTool, tool_call


def _definition(*, tools, denied=()) -> AgentDefinition:
    source = AgentDefinitionSource(
        AgentDefinitionLayer.PROJECT,
        Path("."),
        Path("reviewer.md"),
        "reviewer",
        "project",
    )
    return AgentDefinition(
        "reviewer",
        "review",
        tuple(tools),
        tuple(denied),
        "inherit",
        20,
        PermissionMode.DEFAULT,
        "review",
        source,
    )


def test_defined_scope_is_ordered_intersection_with_deny_precedence() -> None:
    registry = ToolRegistry(
        [
            ControlledTool("first"),
            ControlledTool("write", ToolSafety.SIDE_EFFECT),
            ControlledTool("agent"),
            ControlledTool("last"),
        ]
    )
    scope = build_defined_tool_scope(
        registry,
        _definition(tools=("last", "agent", "write", "first"), denied=("last",)),
        parent_mode_names={"first", "write", "agent", "last"},
        background_capable_names={"last", "first", "write", "agent"},
        allowed_safety={ToolSafety.READ_ONLY},
    )

    assert scope.registry.names == ("first",)
    assert scope.policy.executable_names == frozenset({"first"})


def test_defined_scope_empty_allowlist_never_expands() -> None:
    registry = ToolRegistry([ControlledTool("read")])
    scope = build_defined_tool_scope(
        registry,
        _definition(tools=()),
        parent_mode_names={"read"},
        background_capable_names={"read"},
        allowed_safety={ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT},
    )
    assert scope.registry.names == ()
    assert scope.policy.executable_names == frozenset()


def test_fork_policy_preserves_schema_but_denies_each_boundary_reason() -> None:
    tools = [
        ControlledTool("read"),
        ControlledTool("write", ToolSafety.SIDE_EFFECT),
        ControlledTool("late"),
        ControlledTool("agent"),
        ControlledTool("load_skill"),
    ]
    parent = ToolRegistry(tools)
    policy = build_fork_tool_policy(
        parent,
        background_capable_names={"read", "write", "agent", "load_skill"},
        parent_mode_names={"read", "write", "agent", "load_skill"},
        allowed_safety={ToolSafety.READ_ONLY},
    )

    assert parent.list() == tools
    assert parent.names == ("read", "write", "late", "agent", "load_skill")
    assert policy.executable_names == frozenset({"read"})
    reasons = policy.denial_reasons
    assert "parent mode" in reasons["write"]
    assert "background-capable" in reasons["late"]
    assert "forbidden" in reasons["agent"]
    assert "forbidden" in reasons["load_skill"]
    call = ValidatedToolCall(tool_call("1", "agent"), tools[3])
    assert policy.evaluate(call, None).allowed is False


def test_fork_policy_with_no_parent_tools_is_empty() -> None:
    policy = build_fork_tool_policy(
        None,
        background_capable_names={"hidden"},
        parent_mode_names={"hidden"},
        allowed_safety={ToolSafety.READ_ONLY},
    )
    assert policy.executable_names == frozenset()
    assert dict(policy.denial_reasons) == {}
