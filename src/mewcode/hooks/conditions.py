from __future__ import annotations

from collections.abc import Mapping, Sequence
import regex

from mewcode.matching import MatchSubjectKind, glob_fullmatch

from .models import (
    DEFAULT_HOOK_LIMITS,
    HookCondition,
    HookConditionClause,
    HookEventContext,
    HookLogic,
    HookMatchKind,
    HookLimits,
)


_MISSING = object()


def resolve_field(values: Mapping[str, object], path: str) -> object:
    current: object = values
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            if not part.isdecimal():
                return _MISSING
            index = int(part)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


class HookConditionMatcher:
    def __init__(self, limits: HookLimits = DEFAULT_HOOK_LIMITS) -> None:
        self._limits = limits

    def matches(
        self,
        condition: HookCondition | None,
        event: HookEventContext,
    ) -> bool:
        if condition is None:
            return True
        results = [self._clause_matches(clause, event) for clause in condition.clauses]
        return all(results) if condition.logic is HookLogic.ALL else any(results)

    def _clause_matches(
        self,
        clause: HookConditionClause,
        event: HookEventContext,
    ) -> bool:
        actual = resolve_field(event.values, clause.field)
        matched = False
        if actual is not _MISSING:
            if clause.match is HookMatchKind.EXACT:
                matched = type(actual) is type(clause.value) and actual == clause.value
            elif isinstance(actual, str) and isinstance(clause.value, str):
                if clause.match is HookMatchKind.GLOB:
                    kind = event.match_kinds.get(clause.field, MatchSubjectKind.TEXT)
                    matched = glob_fullmatch(clause.value, actual, kind)
                else:
                    try:
                        compiled = clause.compiled or regex.compile(clause.value)
                        matched = (
                            compiled.fullmatch(
                                actual, timeout=self._limits.regex_timeout_seconds
                            )
                            is not None
                        )
                    except (regex.error, TimeoutError):
                        matched = False
        return not matched if clause.negate else matched
