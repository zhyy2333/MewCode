from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mewcode.permissions import (
    PermissionEffect,
    PermissionRuleMatcher,
    PermissionRuleSets,
    PermissionRuleStore,
    PermissionSource,
    PermissionTarget,
    RuleScope,
    parse_permission_rule,
)
from mewcode.tools import PermissionTargetKind


KNOWN = {"run_command", "read_file", "write_file"}


def parse(
    expression: str,
    effect: str = "allow",
    scope: RuleScope = RuleScope.PROJECT,
):
    return parse_permission_rule(expression, effect, scope, KNOWN)


def test_permission_target_is_immutable_and_exact_rule_escapes_metacharacters() -> None:
    target = PermissionTarget(
        "run_command", r"echo C:\temp\[*]?.txt", PermissionTargetKind.COMMAND
    )
    assert target.exact_rule() == r"run_command(echo C:\\temp\\\[\*\]\?.txt)"
    with pytest.raises(FrozenInstanceError):
        target.value = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "expression",
    [
        "run_command(git status",
        "run_commandgit status)",
        "(git status)",
        "unknown(value)",
        r"run_command(bad\q)",
        "run_command([])",
        "run_command([abc)",
        "run_command(abc])",
    ],
)
def test_parse_rejects_invalid_rules(expression: str) -> None:
    with pytest.raises(ValueError):
        parse(expression)


def test_parse_allows_parentheses_inside_pattern() -> None:
    rule = parse("run_command(echo (hello))")
    assert rule.pattern == "echo (hello)"
    assert rule.is_exact is True


def test_command_glob_is_case_sensitive_and_matches_whole_command() -> None:
    rule = parse("run_command(git *)")
    assert rule.is_exact is False
    matcher = PermissionRuleMatcher()
    sets = PermissionRuleSets(project=(rule,))
    assert matcher.match(
        PermissionTarget("run_command", "git commit -m hello", PermissionTargetKind.COMMAND),
        sets,
    )
    assert matcher.match(
        PermissionTarget("run_command", "Git status", PermissionTargetKind.COMMAND), sets
    ) is None
    assert matcher.match(
        PermissionTarget("run_command", "prefix git status", PermissionTargetKind.COMMAND),
        sets,
    ) is None


def test_escaped_command_glob_characters_are_literal() -> None:
    rule = parse(r"run_command(echo \*)")
    assert rule.is_exact is True
    target = PermissionTarget("run_command", "echo *", PermissionTargetKind.COMMAND)
    assert PermissionRuleMatcher().match(target, PermissionRuleSets(project=(rule,)))


def test_path_glob_single_star_does_not_cross_segment_but_double_star_does() -> None:
    shallow = parse("read_file(src/*)")
    recursive = parse("read_file(src/**)")
    matcher = PermissionRuleMatcher()
    nested = PermissionTarget("read_file", "src/a/b.py", PermissionTargetKind.PATH)
    assert matcher.match(nested, PermissionRuleSets(project=(shallow,))) is None
    assert matcher.match(nested, PermissionRuleSets(project=(recursive,)))


def test_scope_precedence_stops_at_first_matching_layer() -> None:
    session = parse("run_command(git *)", "allow", RuleScope.SESSION)
    local = parse("run_command(git status)", "deny", RuleScope.PROJECT_LOCAL)
    target = PermissionTarget("run_command", "git status", PermissionTargetKind.COMMAND)
    match = PermissionRuleMatcher().match(
        target, PermissionRuleSets(session=(session,), project_local=(local,))
    )
    assert match is not None
    assert match.rule is session
    assert match.source == PermissionSource.SESSION_RULE


def test_specificity_and_tied_deny_are_order_independent() -> None:
    broad = parse("run_command(git *)", "deny")
    narrow = parse("run_command(git status)", "allow")
    tied_allow = parse("run_command(git stat?s)", "allow")
    tied_deny = parse("run_command(git stat?s)", "deny")
    target = PermissionTarget("run_command", "git status", PermissionTargetKind.COMMAND)
    matcher = PermissionRuleMatcher()
    assert matcher.match(target, PermissionRuleSets(project=(broad, narrow))).rule is narrow
    assert (
        matcher.match(target, PermissionRuleSets(project=(tied_allow, tied_deny))).rule
        is tied_deny
    )


class _Writer:
    def __init__(self) -> None:
        self.result = ()

    def add_local_allow(self, target: PermissionTarget):
        return self.result


def test_store_session_allow_is_deduplicated_and_instance_local() -> None:
    target = PermissionTarget("run_command", "git status", PermissionTargetKind.COMMAND)
    first = PermissionRuleStore(PermissionRuleSets(), _Writer())
    second = PermissionRuleStore(PermissionRuleSets(), _Writer())
    first.add_session_allow(target)
    first.add_session_allow(target)
    assert len(first.snapshot().session) == 1
    assert second.snapshot().session == ()
    assert first.match(target).source == PermissionSource.SESSION_RULE
