from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from mewcode.hooks.diagnostics import HookDiagnosticLogger
from mewcode.hooks.events import make_event
from mewcode.hooks.models import (
    CommandHookAction,
    HookActionOutcome,
    HookCatalog,
    HookCondition,
    HookConditionClause,
    HookDecision,
    HookEvent,
    HookExecutionControl,
    HookLogic,
    HookMatchKind,
    HookOutcomeKind,
    HookRule,
    HookRuleKey,
    HookSource,
    PromptHookAction,
)
from mewcode.hooks.runtime import HookRuntime


class FakeExecutor:
    def __init__(self, outcomes=None, gate: asyncio.Event | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[int] = []
        self.gate = gate
        self.closed = False

    async def execute(self, rule, envelope, *, expects_decision):
        self.calls.append(rule.key.index)
        if self.gate is not None:
            await self.gate.wait()
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return HookActionOutcome(HookOutcomeKind.SUCCESS)

    async def close(self):
        self.closed = True


def _rule(index: int, action, condition=None, source=HookSource.USER):
    return HookRule(HookRuleKey(source, Path("hooks.yaml"), index), HookEvent.TOOL_BEFORE, condition, action)


def _catalog(*rules: HookRule) -> HookCatalog:
    return HookCatalog(tuple(rules), MappingProxyType({HookEvent.TOOL_BEFORE: tuple(rules)}), any(r.key.source is HookSource.PROJECT and isinstance(r.action, CommandHookAction) for r in rules))


def _event(tmp_path: Path):
    return make_event(HookEvent.TOOL_BEFORE, workspace=tmp_path, session_id="s", resumed=False, values={"tool": {"name": "run_command", "arguments": {"command": "ok"}}})


def test_sequence_failure_continues_and_first_deny_stops(tmp_path: Path) -> None:
    async def scenario():
        executor = FakeExecutor(
            [
                HookActionOutcome(HookOutcomeKind.FAILURE),
                HookActionOutcome(HookOutcomeKind.DENIED, HookDecision(True, "no")),
                HookActionOutcome(HookOutcomeKind.SUCCESS),
            ]
        )
        runtime = HookRuntime(
            _catalog(*[_rule(i, CommandHookAction("x")) for i in range(3)]),
            executor,
            workspace=tmp_path,
            session_id="s",
            project_trusted=True,
        )
        result = await runtime.dispatch(_event(tmp_path))
        return executor, result

    executor, result = asyncio.run(scenario())
    assert executor.calls == [0, 1]
    assert result.decision == HookDecision(True, "no")


def test_not_matched_prompt_order_and_consume_once(tmp_path: Path) -> None:
    condition = HookCondition(
        HookLogic.ALL,
        (HookConditionClause("tool.name", HookMatchKind.EXACT, "other"),),
    )
    rules = (
        _rule(0, PromptHookAction("miss"), condition),
        _rule(1, PromptHookAction("first")),
        _rule(2, PromptHookAction("second")),
    )

    async def scenario():
        runtime = HookRuntime(_catalog(*rules), FakeExecutor(), workspace=tmp_path, session_id="s", project_trusted=True)
        await runtime.dispatch(_event(tmp_path))
        return runtime.consume_prompt_context(), runtime.consume_prompt_context()

    first, second = asyncio.run(scenario())
    assert first == ("first", "second")
    assert second == ()


def test_once_is_atomic_even_when_failure(tmp_path: Path) -> None:
    async def scenario():
        executor = FakeExecutor([HookActionOutcome(HookOutcomeKind.FAILURE)])
        rule = _rule(0, CommandHookAction("x", control=HookExecutionControl(once=True)))
        runtime = HookRuntime(_catalog(rule), executor, workspace=tmp_path, session_id="s", project_trusted=True)
        await asyncio.gather(*(runtime.dispatch(_event(tmp_path)) for _ in range(5)))
        return executor.calls

    assert asyncio.run(scenario()) == [0]


def test_untrusted_only_skips_project_external(tmp_path: Path) -> None:
    rules = (
        _rule(0, CommandHookAction("x"), source=HookSource.PROJECT),
        _rule(1, PromptHookAction("safe"), source=HookSource.PROJECT),
        _rule(2, CommandHookAction("x"), source=HookSource.USER),
    )

    async def scenario():
        executor = FakeExecutor()
        runtime = HookRuntime(_catalog(*rules), executor, workspace=tmp_path, session_id="s", project_trusted=False)
        await runtime.dispatch(_event(tmp_path))
        return executor.calls, runtime.consume_prompt_context(), runtime.trust_required

    calls, prompts, required = asyncio.run(scenario())
    assert calls == [2]
    assert prompts == ("safe",)
    assert required is False


def test_background_nonblocking_and_close(tmp_path: Path) -> None:
    async def scenario():
        gate = asyncio.Event()
        executor = FakeExecutor(gate=gate)
        rule = _rule(0, CommandHookAction("x", control=HookExecutionControl(background=True)))
        runtime = HookRuntime(_catalog(rule), executor, workspace=tmp_path, session_id="s", project_trusted=True)
        await asyncio.wait_for(runtime.dispatch(_event(tmp_path)), timeout=0.2)
        assert executor.calls == [] or executor.calls == [0]
        gate.set()
        await runtime.close()
        return executor.closed

    assert asyncio.run(scenario())


def test_diagnostic_is_lazy_bounded_and_redacted(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "hooks.jsonl"
    logger = HookDiagnosticLogger(path, sensitive_values=("supersecret",))
    assert not path.exists()
    rule = _rule(0, CommandHookAction("x"))
    runtime = HookRuntime(_catalog(rule), FakeExecutor([HookActionOutcome(HookOutcomeKind.FAILURE, summary="supersecret\nfailed")]), workspace=tmp_path, session_id="s", project_trusted=True, diagnostics=logger)
    asyncio.run(runtime.dispatch(_event(tmp_path)))
    text = path.read_text(encoding="utf-8")
    assert "supersecret" not in text
    assert "[redacted] failed" in text


def test_scope_restores_after_nested_binding(tmp_path: Path) -> None:
    runtime = HookRuntime.empty(tmp_path, "s")
    assert runtime.scope == {}
    with runtime.bind_scope(turn_id="t", component="agent"):
        assert runtime.scope["turn_id"] == "t"
        with runtime.bind_scope(iteration=2):
            assert runtime.scope["iteration"] == 2
        assert "iteration" not in runtime.scope
    assert runtime.scope == {}
