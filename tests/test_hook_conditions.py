from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

from mewcode.hooks import (
    HookCondition,
    HookConditionClause,
    HookConditionMatcher,
    HookEvent,
    HookEventContext,
    HookLogic,
    HookMatchKind,
)


def _event() -> HookEventContext:
    return HookEventContext(
        HookEvent.TOOL_BEFORE,
        datetime.now(timezone.utc),
        MappingProxyType(
            {
                "tool": {
                    "name": "run_command",
                    "arguments": {"command": "git push", "items": ["zero", "one"]},
                }
            }
        ),
    )


def test_unconditional_all_any_and_nested_paths() -> None:
    matcher = HookConditionMatcher()
    event = _event()
    exact = HookConditionClause("tool.name", HookMatchKind.EXACT, "run_command")
    nested = HookConditionClause("tool.arguments.items.1", HookMatchKind.GLOB, "o*")
    missing = HookConditionClause("tool.arguments.absent", HookMatchKind.EXACT, "x")
    assert matcher.matches(None, event)
    assert matcher.matches(HookCondition(HookLogic.ALL, (exact, nested)), event)
    assert matcher.matches(HookCondition(HookLogic.ANY, (missing, nested)), event)


def test_exact_is_type_strict_and_missing_negate() -> None:
    matcher = HookConditionMatcher()
    event = HookEventContext(
        HookEvent.TOOL_BEFORE,
        datetime.now(timezone.utc),
        MappingProxyType({"tool": {"arguments": {"flag": True, "count": 1}}}),
    )
    assert not matcher.matches(
        HookCondition(HookLogic.ALL, (HookConditionClause("tool.arguments.count", HookMatchKind.EXACT, True),)),
        event,
    )
    assert matcher.matches(
        HookCondition(HookLogic.ALL, (HookConditionClause("tool.arguments.missing", HookMatchKind.EXACT, "x", True),)),
        event,
    )


def test_regex_is_full_match() -> None:
    matcher = HookConditionMatcher()
    clause = HookConditionClause("tool.arguments.command", HookMatchKind.REGEX, r"git\s+push")
    assert matcher.matches(HookCondition(HookLogic.ALL, (clause,)), _event())
    partial = HookConditionClause("tool.arguments.command", HookMatchKind.REGEX, "push")
    assert not matcher.matches(HookCondition(HookLogic.ALL, (partial,)), _event())
