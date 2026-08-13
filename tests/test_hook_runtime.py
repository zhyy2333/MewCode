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
    HookLimits,
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


def test_executor_exception_does_not_skip_later_rule(tmp_path: Path) -> None:
    async def scenario():
        executor = FakeExecutor(
            [RuntimeError("hook bug"), HookActionOutcome(HookOutcomeKind.SUCCESS)]
        )
        runtime = HookRuntime(
            _catalog(*[_rule(i, CommandHookAction("x")) for i in range(2)]),
            executor,
            workspace=tmp_path,
            session_id="s",
            project_trusted=True,
        )
        await runtime.dispatch(_event(tmp_path))
        return executor.calls

    assert asyncio.run(scenario()) == [0, 1]


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


def test_diagnostic_rotation_keeps_three_history_files(tmp_path: Path) -> None:
    path = tmp_path / "hooks.jsonl"
    limits = HookLimits(log_bytes=300, log_backups=3)
    logger = HookDiagnosticLogger(path, limits=limits)
    rule = _rule(0, CommandHookAction("x"))
    runtime = HookRuntime(
        _catalog(rule),
        FakeExecutor(
            [HookActionOutcome(HookOutcomeKind.FAILURE, summary="x" * 180)] * 10
        ),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
        diagnostics=logger,
        limits=limits,
    )

    async def scenario() -> None:
        for _ in range(10):
            await runtime.dispatch(_event(tmp_path))

    asyncio.run(scenario())
    files = [path, *(path.with_name(f"hooks.jsonl.{i}") for i in range(1, 4))]
    assert all(item.exists() for item in files)
    for item in files:
        for line in item.read_text(encoding="utf-8").splitlines():
            __import__("json").loads(line)


def test_scope_restores_after_nested_binding(tmp_path: Path) -> None:
    runtime = HookRuntime.empty(tmp_path, "s")
    assert runtime.scope == {}


def test_subagent_scope_is_bounded_and_serialized_without_task_content(
    tmp_path: Path,
) -> None:
    envelopes = []

    class RecordingExecutor(FakeExecutor):
        async def execute(self, rule, envelope, *, expects_decision):
            envelopes.append(envelope)
            return HookActionOutcome(HookOutcomeKind.SUCCESS)

    runtime = HookRuntime(
        _catalog(_rule(0, CommandHookAction("x"))),
        RecordingExecutor(),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )

    with runtime.bind_scope(
        subagent_task_id="t" * 200,
        parent_run_id="parent-run",
        component="subagent",
    ):
        asyncio.run(runtime.dispatch(_event(tmp_path)))

    payload = envelopes[0].value
    assert payload["task"]["id"] == "t" * 128
    assert payload["task"]["parent_run_id"] == "parent-run"
    assert payload["task"]["component"] == "subagent"
    assert "task_text" not in str(payload)
    with runtime.bind_scope(turn_id="t", component="agent"):
        assert runtime.scope["turn_id"] == "t"
        with runtime.bind_scope(iteration=2):
            assert runtime.scope["iteration"] == 2
        assert "iteration" not in runtime.scope
    assert runtime.scope == {}


def test_scope_is_isolated_between_concurrent_runs(tmp_path: Path) -> None:
    runtime = HookRuntime.empty(tmp_path, "s")

    async def worker(run_id: str, iteration: int):
        with runtime.bind_scope(run_id=run_id):
            runtime.update_scope(iteration=iteration)
            await asyncio.sleep(0)
            return runtime.scope

    async def scenario():
        return await asyncio.gather(worker("a", 1), worker("b", 2))

    first, second = asyncio.run(scenario())
    assert first == {"run_id": "a", "iteration": 1}
    assert second == {"run_id": "b", "iteration": 2}
    assert runtime.scope == {}


def test_prompt_and_background_limits_are_bounded(tmp_path: Path) -> None:
    async def scenario():
        gate = asyncio.Event()
        executor = FakeExecutor(gate=gate)
        limits = HookLimits(prompt_consume_bytes=5, background_tasks=1, close_timeout_seconds=0.01)
        prompt_rules = (
            _rule(0, PromptHookAction("1234")),
            _rule(1, PromptHookAction("5678")),
        )
        background_rules = (
            _rule(2, CommandHookAction("x", control=HookExecutionControl(background=True))),
            _rule(3, CommandHookAction("x", control=HookExecutionControl(background=True))),
        )
        runtime = HookRuntime(
            _catalog(*prompt_rules, *background_rules),
            executor,
            workspace=tmp_path,
            session_id="s",
            project_trusted=True,
            limits=limits,
        )
        await runtime.dispatch(_event(tmp_path))
        prompts = runtime.consume_prompt_context()
        gate.set()
        await runtime.close()
        return prompts, executor.calls

    prompts, calls = asyncio.run(scenario())
    assert prompts == ("1234",)
    assert calls == [2]


def test_prompt_queues_are_partitioned_by_subagent_task(tmp_path: Path) -> None:
    rule = _rule(0, PromptHookAction("queued"))
    runtime = HookRuntime(
        _catalog(rule),
        FakeExecutor(),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )

    async def scenario() -> tuple[tuple[str, ...], ...]:
        await runtime.dispatch(_event(tmp_path))
        with runtime.bind_scope(subagent_task_id="a"):
            await runtime.dispatch(_event(tmp_path))
        with runtime.bind_scope(subagent_task_id="b"):
            await runtime.dispatch(_event(tmp_path))
        return (
            runtime.consume_prompt_context("b"),
            runtime.consume_prompt_context(),
            runtime.consume_prompt_context("a"),
        )

    assert asyncio.run(scenario()) == (("queued",), ("queued",), ("queued",))


def test_task_prompt_budget_preserve_and_cleanup(tmp_path: Path) -> None:
    rules = (
        _rule(0, PromptHookAction("1234")),
        _rule(1, PromptHookAction("5678")),
    )
    runtime = HookRuntime(
        _catalog(*rules),
        FakeExecutor(),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
        limits=HookLimits(prompt_consume_bytes=5),
    )

    async def scenario() -> tuple[tuple[str, ...], tuple[str, ...]]:
        with runtime.bind_scope(subagent_task_id="task"):
            await runtime.dispatch(_event(tmp_path))
        preserved = runtime.consume_prompt_context(
            "task", preserve_fork_prefix=True
        )
        queued = runtime.consume_prompt_context("task")
        with runtime.bind_scope(subagent_task_id="cleanup"):
            await runtime.dispatch(_event(tmp_path))
        runtime.cleanup_task_prompts("cleanup")
        assert runtime.consume_prompt_context("cleanup") == ()
        await runtime.close()
        return preserved, queued

    assert asyncio.run(scenario()) == ((), ("1234",))


def test_once_resets_only_for_new_runtime_process_state(tmp_path: Path) -> None:
    rule = _rule(
        0,
        CommandHookAction("x", control=HookExecutionControl(once=True)),
    )

    async def scenario():
        first_executor = FakeExecutor([HookActionOutcome(HookOutcomeKind.FAILURE)])
        first = HookRuntime(
            _catalog(rule),
            first_executor,
            workspace=tmp_path,
            session_id="s",
            project_trusted=True,
        )
        await first.dispatch(_event(tmp_path))
        await first.dispatch(_event(tmp_path))
        await first.close()
        second_executor = FakeExecutor()
        second = HookRuntime(
            _catalog(rule),
            second_executor,
            workspace=tmp_path,
            session_id="s",
            project_trusted=True,
        )
        await second.dispatch(_event(tmp_path))
        await second.close()
        return first_executor.calls, second_executor.calls

    first_calls, second_calls = asyncio.run(scenario())
    assert first_calls == [0]
    assert second_calls == [0]
