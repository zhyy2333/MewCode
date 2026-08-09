from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import re
from typing import Iterable, Protocol

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


@dataclass(frozen=True)
class _Token:
    value: str
    escaped: bool = False


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
    if tool_name not in known_tools:
        raise PermissionRuleError(f"Unknown tool in permission rule: {tool_name}")
    if pattern == "":
        raise PermissionRuleError("Rule pattern must not be empty.")

    try:
        parsed_effect = PermissionEffect(effect)
    except (TypeError, ValueError) as exc:
        raise PermissionRuleError("Rule result must be 'allow' or 'deny'.") from exc

    tokens = _tokenize(pattern)
    is_exact = not any(
        not token.escaped and token.value in {"*", "?", "["} for token in tokens
    )
    _validate_character_classes(tokens)
    fixed_text = sum(
        len(token.value)
        for token in tokens
        if token.escaped or token.value not in {"*", "?", "[", "]"}
    )
    segment_count = pattern.count("/") + 1
    return PermissionRule(
        tool_name=tool_name,
        pattern=pattern,
        effect=parsed_effect,
        scope=scope,
        is_exact=is_exact,
        specificity=(int(is_exact), fixed_text, segment_count),
    )


def _tokenize(pattern: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character != "\\":
            tokens.append(_Token(character))
            index += 1
            continue
        if index + 1 >= len(pattern) or pattern[index + 1] not in "\\*?[]":
            raise PermissionRuleError(
                "Rule contains an invalid escape; use \\\\, \\*, \\?, \\[ or \\]."
            )
        tokens.append(_Token(pattern[index + 1], escaped=True))
        index += 2
    return tuple(tokens)


def _validate_character_classes(tokens: tuple[_Token, ...]) -> None:
    inside = False
    content = 0
    for token in tokens:
        if token.escaped:
            if inside:
                content += 1
            continue
        if token.value == "[":
            if inside:
                raise PermissionRuleError("Nested character classes are not supported.")
            inside = True
            content = 0
        elif token.value == "]":
            if not inside:
                raise PermissionRuleError("Rule contains an unmatched ']'.")
            if content == 0:
                raise PermissionRuleError("Rule contains an empty character class.")
            inside = False
        elif inside:
            content += 1
    if inside:
        raise PermissionRuleError("Rule contains an unmatched '['.")


def _compile_pattern(pattern: str, kind: PermissionTargetKind) -> re.Pattern[str]:
    tokens = _tokenize(pattern)
    _validate_character_classes(tokens)
    parts = ["^"]
    index = 0
    path_mode = kind in {PermissionTargetKind.PATH, PermissionTargetKind.PATH_GLOB}
    star = "[^/]*" if path_mode else ".*"
    question = "[^/]" if path_mode else "."
    while index < len(tokens):
        token = tokens[index]
        if token.escaped:
            parts.append(re.escape(token.value))
        elif token.value == "*":
            if path_mode and index + 1 < len(tokens) and tokens[index + 1] == _Token("*"):
                if index + 2 < len(tokens) and tokens[index + 2] == _Token("/"):
                    parts.append("(?:.*/)?")
                    index += 2
                else:
                    parts.append(".*")
                    index += 1
            else:
                parts.append(star)
        elif token.value == "?":
            parts.append(question)
        elif token.value == "[":
            class_parts: list[str] = []
            index += 1
            while index < len(tokens) and not (
                tokens[index].value == "]" and not tokens[index].escaped
            ):
                value = tokens[index].value
                if value in {"\\", "]", "^"}:
                    value = "\\" + value
                class_parts.append(value)
                index += 1
            prefix = "(?!/)" if path_mode else ""
            parts.append(prefix + "[" + "".join(class_parts) + "]")
        else:
            parts.append(re.escape(token.value))
        index += 1
    parts.append("$")
    flags = re.IGNORECASE if path_mode and os.name == "nt" else 0
    return re.compile("".join(parts), flags)


def rule_matches(rule: PermissionRule, target: PermissionTarget) -> bool:
    if rule.tool_name != target.tool_name:
        return False
    return _compile_pattern(rule.pattern, target.kind).fullmatch(target.value) is not None


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
