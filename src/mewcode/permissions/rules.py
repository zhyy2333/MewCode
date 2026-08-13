from __future__ import annotations

import asyncio
from typing import Iterable, Protocol

from mewcode.matching import (
    GlobPatternError,
    MatchSubjectKind,
    glob_fullmatch,
    glob_is_exact,
    glob_specificity,
)
from mewcode.tools import PermissionTargetKind

from .models import (
    PermissionEffect,
    PermissionMatch,
    PermissionRule,
    PermissionRuleSets,
    PermissionSource,
    PermissionTarget,
    RuleScope,
)


class PermissionRuleError(ValueError):
    pass


class LocalRuleWriter(Protocol):
    def add_local_allow(self, target: PermissionTarget) -> tuple[PermissionRule, ...]:
        ...


_SOURCE_BY_SCOPE = {
    RuleScope.SESSION: PermissionSource.SESSION_RULE,
    RuleScope.PROJECT_LOCAL: PermissionSource.PROJECT_LOCAL_RULE,
    RuleScope.PROJECT: PermissionSource.PROJECT_RULE,
    RuleScope.USER: PermissionSource.USER_RULE,
}


def parse_permission_rule(
    expression: str,
    effect: PermissionEffect | str,
    scope: RuleScope,
    known_tools: set[str],
    deferred_tool_prefixes: tuple[str, ...] = (),
) -> PermissionRule:
    if not isinstance(expression, str) or not expression:
        raise PermissionRuleError("Rule expression must be a non-empty string.")
    opening = expression.find("(")
    if opening <= 0 or not expression.endswith(")"):
        raise PermissionRuleError("Rule must use tool_name(pattern) syntax.")
    tool_name = expression[:opening]
    pattern = expression[opening + 1 : -1]
    if not tool_name or tool_name.strip() != tool_name:
        raise PermissionRuleError("Rule tool name must be non-empty without whitespace.")
    if tool_name not in known_tools and not any(
        tool_name.startswith(prefix) for prefix in deferred_tool_prefixes
    ):
        raise PermissionRuleError(f"Unknown tool in permission rule: {tool_name}")
    if pattern == "":
        raise PermissionRuleError("Rule pattern must not be empty.")

    try:
        parsed_effect = PermissionEffect(effect)
    except (TypeError, ValueError) as exc:
        raise PermissionRuleError("Rule result must be 'allow' or 'deny'.") from exc

    try:
        is_exact = glob_is_exact(pattern)
        specificity = glob_specificity(pattern)
    except GlobPatternError as exc:
        raise PermissionRuleError(str(exc).replace("Glob", "Rule")) from exc
    return PermissionRule(
        tool_name=tool_name,
        pattern=pattern,
        effect=parsed_effect,
        scope=scope,
        is_exact=is_exact,
        specificity=specificity,
    )


def rule_matches(rule: PermissionRule, target: PermissionTarget) -> bool:
    if rule.tool_name != target.tool_name:
        return False
    kind = (
        MatchSubjectKind.PATH
        if target.kind in {PermissionTargetKind.PATH, PermissionTargetKind.PATH_GLOB}
        else MatchSubjectKind.TEXT
    )
    return glob_fullmatch(rule.pattern, target.value, kind)


class PermissionRuleMatcher:
    def match(
        self,
        target: PermissionTarget,
        rule_sets: PermissionRuleSets,
    ) -> PermissionMatch | None:
        layers = (
            (RuleScope.SESSION, rule_sets.session),
            (RuleScope.PROJECT_LOCAL, rule_sets.project_local),
            (RuleScope.PROJECT, rule_sets.project),
            (RuleScope.USER, rule_sets.user),
        )
        for scope, rules in layers:
            candidates = [rule for rule in rules if rule_matches(rule, target)]
            if not candidates:
                continue
            winner = max(
                candidates,
                key=lambda rule: (
                    rule.specificity,
                    int(rule.effect == PermissionEffect.DENY),
                ),
            )
            return PermissionMatch(rule=winner, source=_SOURCE_BY_SCOPE[scope])
        return None


class PermissionRuleStore:
    def __init__(
        self,
        rule_sets: PermissionRuleSets,
        local_writer: LocalRuleWriter,
        matcher: PermissionRuleMatcher | None = None,
    ) -> None:
        self._rule_sets = rule_sets
        self._local_writer = local_writer
        self._matcher = matcher or PermissionRuleMatcher()

    def snapshot(self) -> PermissionRuleSets:
        return self._rule_sets

    def match(self, target: PermissionTarget) -> PermissionMatch | None:
        return self._matcher.match(target, self._rule_sets)

    def add_session_allow(self, target: PermissionTarget) -> None:
        rule = parse_permission_rule(
            target.exact_rule(),
            PermissionEffect.ALLOW,
            RuleScope.SESSION,
            {target.tool_name},
        )
        if rule not in self._rule_sets.session:
            self._rule_sets = PermissionRuleSets(
                session=self._rule_sets.session + (rule,),
                project_local=self._rule_sets.project_local,
                project=self._rule_sets.project,
                user=self._rule_sets.user,
            )

    async def persist_project_local_allow(self, target: PermissionTarget) -> None:
        updated = await asyncio.to_thread(self._local_writer.add_local_allow, target)
        self._rule_sets = PermissionRuleSets(
            session=self._rule_sets.session,
            project_local=tuple(updated),
            project=self._rule_sets.project,
            user=self._rule_sets.user,
        )
