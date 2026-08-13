from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

from mewcode.hooks import (
    HookActionOutcome,
    CommandHookAction,
    HookCatalog,
    HookDecision,
    HookConfigLoader,
    HookEvent,
    HookOutcomeKind,
    HookPaths,
    HookRule,
    HookRuleKey,
    HookRuntime,
    HookSource,
    PromptHookAction,
    make_event,
)
from mewcode.hooks.provider import HookedProvider
from mewcode.agent import AgentRunner, ToolScheduler
from mewcode.conversation import Conversation
from mewcode.providers import ProviderTextDelta, ProviderToolCall
from mewcode.providers import ModelRequest
from mewcode.prompting import PromptPackage
from mewcode.tools import ToolRegistry
from fakes import (
    AllowAllPermissionController,
    ControlledTool,
    ScriptedAsyncProvider,
    collect_async,
    tool_call,
)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict[str, object]]] = []

    async def execute(self, rule, envelope, *, expects_decision):
        self.calls.append(
            (rule.key.source.value, rule.key.index, json.loads(envelope.encoded))
        )
        return HookActionOutcome(HookOutcomeKind.SUCCESS)

    async def close(self):
        return None


class DenyingToolExecutor(RecordingExecutor):
    async def execute(self, rule, envelope, *, expects_decision):
        payload = json.loads(envelope.encoded)
        self.calls.append((rule.key.source.value, rule.key.index, payload))
        if payload["event"] == "tool.before":
            return HookActionOutcome(
                HookOutcomeKind.DENIED,
                HookDecision(True, "use a read-only alternative"),
            )
        return HookActionOutcome(HookOutcomeKind.SUCCESS)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_three_layer_config_conditions_trust_and_runtime_order(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    paths = HookPaths.for_workspace(workspace, user_home=tmp_path / "home")
    common = """hooks:
- event: tool.before
  if:
    all:
      - {field: tool.name, match: exact, value: run_command}
      - {field: tool.arguments.command, match: glob, value: 'git *'}
  action: {type: command, command: echo checked}
"""
    _write(paths.user, common)
    _write(paths.project, common)
    _write(paths.project_local, common)
    catalog = HookConfigLoader().load(paths)
    executor = RecordingExecutor()
    runtime = HookRuntime(
        catalog,
        executor,
        workspace=workspace,
        session_id="s",
        project_trusted=False,
    )
    event = make_event(
        HookEvent.TOOL_BEFORE,
        workspace=workspace,
        session_id="s",
        resumed=False,
        values={
            "tool": {
                "call_id": "1",
                "name": "run_command",
                "arguments": {"command": "git status"},
                "target": {"kind": "command", "value": "git status"},
            }
        },
    )
    asyncio.run(runtime.dispatch(event))
    assert [(source, index) for source, index, _ in executor.calls] == [
        ("user", 0),
        ("project_local", 0),
    ]
    assert all(call[2]["tool"]["arguments"]["command"] == "git status" for call in executor.calls)


def test_repository_hook_example_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    rules = HookConfigLoader().load_file(
        root / "examples" / "hooks.yaml",
        __import__("mewcode.hooks", fromlist=["HookSource"]).HookSource.USER,
    )
    assert len(rules) == 4
    assert {rule.event for rule in rules} >= {
        HookEvent.SESSION_START,
        HookEvent.TOOL_BEFORE,
        HookEvent.TURN_END,
    }


def test_two_provider_calls_one_tool_have_exact_paired_lifecycle(tmp_path: Path) -> None:
    event_names = (
        HookEvent.SESSION_START,
        HookEvent.SESSION_END,
        HookEvent.TURN_START,
        HookEvent.TURN_END,
        HookEvent.MESSAGE_BEFORE,
        HookEvent.MESSAGE_AFTER,
        HookEvent.TOOL_BEFORE,
        HookEvent.TOOL_AFTER,
    )
    rules = tuple(
        HookRule(
            HookRuleKey(HookSource.USER, Path("h"), index),
            event,
            None,
            CommandHookAction("ignored"),
        )
        for index, event in enumerate(event_names)
    )
    executor = RecordingExecutor()
    runtime = HookRuntime(
        HookCatalog(
            rules,
            MappingProxyType(
                {event: tuple(rule for rule in rules if rule.event is event) for event in event_names}
            ),
        ),
        executor,
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )
    provider = HookedProvider(
        ScriptedAsyncProvider(
            [
                [ProviderToolCall(tool_call("1", "read", value="x"))],
                [ProviderTextDelta("done")],
            ]
        ),
        runtime,
        "main",
    )
    scheduler = ToolScheduler(
        AllowAllPermissionController(), hook_runtime=runtime
    )
    runner = AgentRunner(provider, scheduler, hook_runtime=runtime)
    conversation = Conversation(
        runner,
        ToolRegistry([ControlledTool("read")]),
        hook_runtime=runtime,
    )

    async def scenario() -> None:
        await conversation.start()
        await collect_async(conversation.ask("inspect"))
        await conversation.close()

    asyncio.run(scenario())
    names = [payload["event"] for _, _, payload in executor.calls]
    assert names == [
        "session.start",
        "turn.start",
        "message.before",
        "message.after",
        "tool.before",
        "tool.after",
        "message.before",
        "message.after",
        "turn.end",
        "session.end",
    ]
    scoped = [payload for _, _, payload in executor.calls if payload["event"].startswith(("message.", "tool."))]
    assert len({payload["turn"]["id"] for payload in scoped}) == 1
    assert [payload["message"]["iteration"] for payload in scoped if payload["event"] == "message.before"] == [1, 2]


def test_hook_deny_returns_tool_result_and_model_adjusts_next_iteration(tmp_path: Path) -> None:
    events = (HookEvent.TOOL_BEFORE, HookEvent.TOOL_AFTER)
    rules = tuple(
        HookRule(
            HookRuleKey(HookSource.USER, Path("h"), index),
            event,
            None,
            CommandHookAction("ignored"),
        )
        for index, event in enumerate(events)
    )
    executor = DenyingToolExecutor()
    runtime = HookRuntime(
        HookCatalog(
            rules,
            MappingProxyType({event: (rules[index],) for index, event in enumerate(events)}),
        ),
        executor,
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )
    base = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call("1", "write", value="unsafe"))],
            [ProviderTextDelta("used a safer approach")],
        ]
    )
    tool = ControlledTool("write")
    conversation = Conversation(
        AgentRunner(
            HookedProvider(base, runtime, "main"),
            ToolScheduler(AllowAllPermissionController(), hook_runtime=runtime),
            hook_runtime=runtime,
        ),
        ToolRegistry([tool]),
        hook_runtime=runtime,
    )
    asyncio.run(collect_async(conversation.ask("change it")))
    assert tool.calls == []
    assert "Hook denied" in str(base.calls[1].messages[-1].content)
    assert "use a read-only alternative" in str(base.calls[1].messages[-1].content)
    assert [payload["event"] for _, _, payload in executor.calls] == [
        "tool.before",
        "tool.after",
    ]
    assert executor.calls[-1][2]["tool"]["status"] == "denied"


def test_prompt_sources_are_consumed_by_only_the_next_provider_request(tmp_path: Path) -> None:
    prompt_events = (
        (HookEvent.SESSION_START, "from-session"),
        (HookEvent.TURN_START, "from-turn"),
        (HookEvent.MESSAGE_BEFORE, "from-message"),
        (HookEvent.TOOL_AFTER, "from-tool"),
        (HookEvent.COMPACT_BEFORE, "from-compact"),
    )
    rules = tuple(
        HookRule(
            HookRuleKey(HookSource.USER, Path("h"), index),
            event,
            None,
            PromptHookAction(content),
        )
        for index, (event, content) in enumerate(prompt_events)
    )
    runtime = HookRuntime(
        HookCatalog(
            rules,
            MappingProxyType(
                {event: tuple(rule for rule in rules if rule.event is event) for event, _ in prompt_events}
            ),
        ),
        RecordingExecutor(),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )
    base = ScriptedAsyncProvider([[ProviderTextDelta(str(i))] for i in range(4)])
    hooked = HookedProvider(base, runtime, "main")
    request = ModelRequest(PromptPackage("stable", "dynamic"), ())

    async def invoke_after(event: HookEvent, values=None) -> None:
        await runtime.dispatch(
            make_event(
                event,
                workspace=tmp_path,
                session_id="s",
                resumed=False,
                values=values,
            )
        )
        await collect_async(hooked.stream_reply(request))

    async def scenario() -> None:
        await invoke_after(HookEvent.SESSION_START)
        await invoke_after(
            HookEvent.TURN_START,
            {"turn": {"id": "t", "mode": "direct", "input_summary": "x"}},
        )
        await invoke_after(
            HookEvent.TOOL_AFTER,
            {"tool": {"call_id": "1", "name": "read", "arguments": {}, "status": "success", "ok": True}},
        )
        await invoke_after(
            HookEvent.COMPACT_BEFORE,
            {"compaction": {"mode": "manual", "message_count_before": 3}},
        )

    asyncio.run(scenario())
    dynamics = [call.prompt.dynamic_system for call in base.calls]
    assert "from-session" in dynamics[0]
    assert "from-turn" in dynamics[1]
    assert "from-tool" in dynamics[2]
    assert "from-compact" in dynamics[3]
    assert all("from-message" in value for value in dynamics)
    for index, marker in enumerate(("from-session", "from-turn", "from-tool", "from-compact")):
        assert sum(marker in value for value in dynamics) == 1
    assert request.prompt.dynamic_system == "dynamic"
