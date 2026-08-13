from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import MappingProxyType

import httpx
import pytest

from mewcode.hooks.actions import HookActionExecutor
from mewcode.hooks.events import make_event, serialize_event
from mewcode.hooks.models import (
    AgentHookAction,
    CommandHookAction,
    HookEvent,
    HookExecutionControl,
    HookOutcomeKind,
    HookRule,
    HookRuleKey,
    HookSource,
    HttpHookAction,
    PromptHookAction,
)


def _rule(action, event: HookEvent = HookEvent.TURN_END) -> HookRule:
    return HookRule(
        HookRuleKey(HookSource.USER, Path("hooks.yaml"), 0), event, None, action
    )


def _envelope(tmp_path: Path):
    return serialize_event(
        make_event(
            HookEvent.TOOL_BEFORE,
            workspace=tmp_path,
            session_id="s",
            resumed=False,
            values={"tool": {"name": "run_command", "arguments": {"command": "x"}}},
        )
    )


def _decision_command(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload).replace('"', '\\"')
    return f'{sys.executable} -c "print(\'{encoded}\')"'


def test_command_receives_envelope_and_decision(tmp_path: Path) -> None:
    action = CommandHookAction(_decision_command({"decision": "deny", "reason": "blocked"}))
    outcome = asyncio.run(
        HookActionExecutor(tmp_path).execute(
            _rule(action, HookEvent.TOOL_BEFORE), _envelope(tmp_path), expects_decision=True
        )
    )
    assert outcome.kind is HookOutcomeKind.DENIED
    assert outcome.decision is not None and outcome.decision.reason == "blocked"


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "maybe"},
        {"decision": "deny"},
        {"decision": "allow", "reason": "extra"},
    ],
)
def test_invalid_command_decisions_fail_open(tmp_path: Path, payload) -> None:
    outcome = asyncio.run(
        HookActionExecutor(tmp_path).execute(
            _rule(CommandHookAction(_decision_command(payload)), HookEvent.TOOL_BEFORE),
            _envelope(tmp_path),
            expects_decision=True,
        )
    )
    assert outcome.kind is HookOutcomeKind.FAILURE
    assert outcome.decision is None


def test_http_success_and_body_is_envelope(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"decision": "allow"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            executor = HookActionExecutor(tmp_path, http_client=client)
            return await executor.execute(
                _rule(HttpHookAction("https://user:pass@example.test/h?secret=x"), HookEvent.TOOL_BEFORE),
                _envelope(tmp_path),
                expects_decision=True,
            )

    outcome = asyncio.run(scenario())
    assert outcome.kind is HookOutcomeKind.SUCCESS
    assert outcome.decision is not None and not outcome.decision.deny
    assert json.loads(requests[0].content)["event"] == "tool.before"
    assert "secret=x" not in outcome.summary
    assert "user:pass" not in outcome.summary


def test_http_non_2xx_is_isolated(tmp_path: Path) -> None:
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503, text="secret body"))
        ) as client:
            return await HookActionExecutor(tmp_path, http_client=client).execute(
                _rule(HttpHookAction("https://example.test/h")),
                _envelope(tmp_path),
                expects_decision=False,
            )

    outcome = asyncio.run(scenario())
    assert outcome.kind is HookOutcomeKind.FAILURE
    assert "secret body" not in outcome.summary


def test_prompt_and_agent_do_not_start_external_work(tmp_path: Path) -> None:
    executor = HookActionExecutor(tmp_path)
    prompt = asyncio.run(
        executor.execute(_rule(PromptHookAction("context")), _envelope(tmp_path), expects_decision=False)
    )
    agent = asyncio.run(
        executor.execute(_rule(AgentHookAction("task")), _envelope(tmp_path), expects_decision=False)
    )
    assert prompt.kind is HookOutcomeKind.SUCCESS
    assert agent.kind is HookOutcomeKind.SKIPPED
