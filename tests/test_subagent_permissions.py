from __future__ import annotations

import asyncio

import pytest

from mewcode.permissions import (
    PermissionChoice,
    PermissionEffect,
    PermissionMode,
    PermissionOutcome,
    PermissionRuleSets,
    PermissionRuleStore,
    PermissionSource,
    RuleScope,
    parse_permission_rule,
)
from mewcode.subagents import (
    SubagentPermissionController,
    persistent_permission_snapshot,
)
from mewcode.tools import ToolRegistry, ValidatedToolCall, Workspace
from tests.fakes import ControlledTool, tool_call


class Writer:
    def add_local_allow(self, target):
        raise AssertionError("subagents must not persist permission rules")


def _rule(effect: PermissionEffect, scope: RuleScope, pattern: str = "test"):
    return parse_permission_rule(
        f"run({pattern})", effect, scope, {"run"}
    )


def _call() -> ValidatedToolCall:
    tool = ControlledTool("run")
    return ValidatedToolCall(tool_call("1", "run", value="test"), tool)


def _controller(tmp_path, sets, mode):
    parent = PermissionRuleStore(sets, Writer())
    return parent, SubagentPermissionController.from_parent(
        Workspace(tmp_path), parent, mode
    )


def test_persistent_snapshot_copies_three_layers_and_clears_session() -> None:
    sets = PermissionRuleSets(
        session=(_rule(PermissionEffect.ALLOW, RuleScope.SESSION),),
        project_local=(_rule(PermissionEffect.ALLOW, RuleScope.PROJECT_LOCAL),),
        project=(_rule(PermissionEffect.DENY, RuleScope.PROJECT),),
        user=(_rule(PermissionEffect.ALLOW, RuleScope.USER),),
    )
    snapshot = persistent_permission_snapshot(sets)
    assert snapshot.session == ()
    assert snapshot.project_local is not sets.project_local
    assert snapshot.project_local == sets.project_local
    assert snapshot.project == sets.project
    assert snapshot.user == sets.user


@pytest.mark.parametrize(
    ("mode", "expected", "source"),
    [
        (PermissionMode.STRICT, PermissionOutcome.DENY, PermissionSource.SUBAGENT_NON_INTERACTIVE),
        (PermissionMode.DEFAULT, PermissionOutcome.ALLOW, PermissionSource.PROJECT_RULE),
        (PermissionMode.ALLOW, PermissionOutcome.ALLOW, PermissionSource.PROJECT_RULE),
    ],
)
def test_noninteractive_controller_rewrites_only_ask(
    tmp_path,
    mode,
    expected,
    source,
) -> None:
    _, controller = _controller(
        tmp_path,
        PermissionRuleSets(project=(_rule(PermissionEffect.ALLOW, RuleScope.PROJECT),)),
        mode,
    )
    decision = controller.evaluate(_call())
    assert decision.outcome is expected
    assert decision.source is source
    assert decision.target is not None


def test_explicit_deny_and_hard_preflight_sources_are_preserved(tmp_path) -> None:
    _, controller = _controller(
        tmp_path,
        PermissionRuleSets(project=(_rule(PermissionEffect.DENY, RuleScope.PROJECT),)),
        PermissionMode.ALLOW,
    )
    denied = controller.evaluate(_call())
    assert denied.outcome is PermissionOutcome.DENY
    assert denied.source is PermissionSource.PROJECT_RULE

    dangerous_tool = ControlledTool("run")
    dangerous = ValidatedToolCall(
        tool_call("2", "run", value="rm -rf /"), dangerous_tool
    )
    hard = controller.preflight(dangerous)
    assert hard.outcome is PermissionOutcome.DENY
    assert hard.source is PermissionSource.BLACKLIST


def test_parent_session_rule_is_not_inherited_and_later_changes_do_not_leak(
    tmp_path,
) -> None:
    parent, controller = _controller(
        tmp_path,
        PermissionRuleSets(),
        PermissionMode.DEFAULT,
    )
    parent.add_session_allow(controller.preflight(_call()).target)
    decision = controller.evaluate(_call())
    assert decision.outcome is PermissionOutcome.DENY
    assert decision.source is PermissionSource.SUBAGENT_NON_INTERACTIVE


def test_apply_choice_is_unreachable(tmp_path) -> None:
    _, controller = _controller(tmp_path, PermissionRuleSets(), PermissionMode.DEFAULT)
    decision = controller.evaluate(_call())
    with pytest.raises(RuntimeError, match="never request"):
        asyncio.run(controller.apply_choice(decision, PermissionChoice.ONCE))
