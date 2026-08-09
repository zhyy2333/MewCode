from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from mewcode.permissions import (
    PermissionChallenge,
    PermissionChoice,
    PermissionController,
    PermissionEffect,
    PermissionMode,
    PermissionOutcome,
    PermissionRuleSets,
    PermissionRuleStore,
    PermissionSource,
    PermissionTargetBuilder,
    RuleScope,
    parse_permission_rule,
)
from mewcode.tools import (
    PermissionTargetKind,
    ToolCallRequest,
    ToolPermissionSpec,
    ValidatedToolCall,
    Workspace,
)


def test_challenge_resolve_before_and_after_wait() -> None:
    async def scenario() -> None:
        first = PermissionChallenge("p1", "c1", "tool", "target")
        first.resolve(PermissionChoice.ONCE)
        assert await first.wait() == PermissionChoice.ONCE

        second = PermissionChallenge("p2", "c2", "tool", "target")
        waiting = asyncio.create_task(second.wait())
        await asyncio.sleep(0)
        second.resolve(PermissionChoice.SESSION)
        assert await waiting == PermissionChoice.SESSION

    asyncio.run(scenario())


def test_challenge_rejects_duplicate_response_and_cancel_wakes_waiter() -> None:
    async def scenario() -> None:
        challenge = PermissionChallenge("p", "c", "tool", "target")
        challenge.resolve(PermissionChoice.DENY)
        with pytest.raises(RuntimeError):
            challenge.resolve(PermissionChoice.ONCE)

        cancelled = PermissionChallenge("p2", "c2", "tool", "target")
        waiting = asyncio.create_task(cancelled.wait())
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

    asyncio.run(scenario())


class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.rules = ()

    def add_local_allow(self, target):
        if self.fail:
            raise RuntimeError("disk unavailable")
        self.rules = (
            parse_permission_rule(
                target.exact_rule(), "allow", RuleScope.PROJECT_LOCAL, {target.tool_name}
            ),
        )
        return self.rules


def _call(command: str = "git status") -> ValidatedToolCall:
    tool = SimpleNamespace(
        name="run_command",
        permission_spec=ToolPermissionSpec("command", PermissionTargetKind.COMMAND),
    )
    request = ToolCallRequest(
        "call", "run_command", {"command": command}, '{"command":"..."}'
    )
    return ValidatedToolCall(request, tool)


def _controller(
    tmp_path: Path,
    mode: PermissionMode,
    effect: PermissionEffect | None,
    scope: RuleScope = RuleScope.PROJECT,
    writer: _Writer | None = None,
) -> tuple[PermissionController, PermissionRuleStore]:
    rules = ()
    if effect is not None:
        rules = (
            parse_permission_rule(
                "run_command(git *)", effect, scope, {"run_command"}
            ),
        )
    sets = PermissionRuleSets(
        session=rules if scope == RuleScope.SESSION else (),
        project=rules if scope == RuleScope.PROJECT else (),
    )
    store = PermissionRuleStore(sets, writer or _Writer())
    controller = PermissionController(
        PermissionTargetBuilder(Workspace(tmp_path)), store, mode
    )
    return controller, store


@pytest.mark.parametrize("mode", list(PermissionMode))
def test_mode_explicit_deny_always_wins(tmp_path: Path, mode: PermissionMode) -> None:
    controller, _ = _controller(tmp_path, mode, PermissionEffect.DENY)
    assert controller.evaluate(_call()).outcome == PermissionOutcome.DENY


@pytest.mark.parametrize("mode", list(PermissionMode))
def test_mode_session_allow_always_allows(tmp_path: Path, mode: PermissionMode) -> None:
    controller, _ = _controller(
        tmp_path, mode, PermissionEffect.ALLOW, RuleScope.SESSION
    )
    assert controller.evaluate(_call()).outcome == PermissionOutcome.ALLOW


@pytest.mark.parametrize(
    ("mode", "effect", "expected"),
    [
        (PermissionMode.STRICT, PermissionEffect.ALLOW, PermissionOutcome.ASK),
        (PermissionMode.STRICT, None, PermissionOutcome.ASK),
        (PermissionMode.DEFAULT, PermissionEffect.ALLOW, PermissionOutcome.ALLOW),
        (PermissionMode.DEFAULT, None, PermissionOutcome.ASK),
        (PermissionMode.ALLOW, PermissionEffect.ALLOW, PermissionOutcome.ALLOW),
        (PermissionMode.ALLOW, None, PermissionOutcome.ALLOW),
    ],
)
def test_mode_persistent_allow_and_unmatched_matrix(
    tmp_path: Path,
    mode: PermissionMode,
    effect: PermissionEffect | None,
    expected: PermissionOutcome,
) -> None:
    controller, _ = _controller(tmp_path, mode, effect)
    assert controller.evaluate(_call()).outcome == expected


def test_apply_once_deny_and_session_choices(tmp_path: Path) -> None:
    controller, store = _controller(tmp_path, PermissionMode.DEFAULT, None)
    decision = controller.evaluate(_call("echo [*]"))
    denied = asyncio.run(controller.apply_choice(decision, PermissionChoice.DENY))
    assert denied.outcome == PermissionOutcome.DENY
    assert denied.source == PermissionSource.USER_CONFIRMATION
    once = asyncio.run(controller.apply_choice(decision, PermissionChoice.ONCE))
    assert once.outcome == PermissionOutcome.ALLOW
    assert store.snapshot().session == ()
    session = asyncio.run(controller.apply_choice(decision, PermissionChoice.SESSION))
    assert session.outcome == PermissionOutcome.ALLOW
    assert store.snapshot().session[0].is_exact
    assert controller.evaluate(_call("echo [*]")).outcome == PermissionOutcome.ALLOW
    assert controller.evaluate(_call("echo x")).outcome == PermissionOutcome.ASK


def test_apply_permanent_updates_both_layers_and_fails_closed(tmp_path: Path) -> None:
    controller, store = _controller(tmp_path, PermissionMode.DEFAULT, None)
    decision = controller.evaluate(_call())
    allowed = asyncio.run(controller.apply_choice(decision, PermissionChoice.PERMANENT))
    assert allowed.outcome == PermissionOutcome.ALLOW
    assert store.snapshot().project_local
    assert store.snapshot().session

    failing, failed_store = _controller(
        tmp_path, PermissionMode.DEFAULT, None, writer=_Writer(fail=True)
    )
    denied = asyncio.run(
        failing.apply_choice(failing.evaluate(_call()), PermissionChoice.PERMANENT)
    )
    assert denied.outcome == PermissionOutcome.DENY
    assert denied.source == PermissionSource.CONFIG_ERROR
    assert failed_store.snapshot().session == ()
