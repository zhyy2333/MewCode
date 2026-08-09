from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.agent import (
    AgentPermissionDecision,
    AgentPermissionRequest,
    AgentRunner,
    AgentStopped,
    AgentToolResult,
    StopReason,
    ToolScheduler,
)
from mewcode.permissions import (
    PermissionChoice,
    PermissionController,
    PermissionMode,
    PermissionOutcome,
    PermissionRuleSets,
    PermissionRuleStore,
    PermissionTargetBuilder,
    RuleScope,
    parse_permission_rule,
)
from mewcode.providers import ProviderTextDelta, ProviderToolCall
from mewcode.tools import ToolRegistry, Workspace
from mewcode.tools import ReadFileTool, RunCommandTool

from tests.fakes import ControlledTool, ScriptedAsyncProvider, collect_async, tool_call


class _Writer:
    def add_local_allow(self, target):
        return (
            parse_permission_rule(
                target.exact_rule(), "allow", RuleScope.PROJECT_LOCAL, {target.tool_name}
            ),
        )


def _controller(
    tmp_path: Path, expressions: list[tuple[str, str]] | None = None
) -> PermissionController:
    rules = tuple(
        parse_permission_rule(expression, effect, RuleScope.PROJECT, {"read-a", "read-b"})
        for expression, effect in (expressions or [])
    )
    store = PermissionRuleStore(PermissionRuleSets(project=rules), _Writer())
    return PermissionController(
        PermissionTargetBuilder(Workspace(tmp_path)), store, PermissionMode.DEFAULT
    )


def test_permission_events_are_desensitized_and_mixed_denial_is_independent(
    tmp_path: Path,
) -> None:
    denied = ControlledTool("read-a")
    allowed = ControlledTool("read-b")
    controller = _controller(
        tmp_path,
        [("read-a(test)", "deny"), ("read-b(test)", "allow")],
    )
    schedule = ToolScheduler(controller).schedule(
        "run",
        1,
        [tool_call("1", "read-a", value="test"), tool_call("2", "read-b", value="test")],
        ToolRegistry([denied, allowed]),
    )
    events = asyncio.run(collect_async(schedule.events()))
    decisions = [event for event in events if isinstance(event, AgentPermissionDecision)]
    assert [(event.tool_name, event.outcome.value) for event in decisions] == [
        ("read-a", "deny"),
        ("read-b", "allow"),
    ]
    assert denied.calls == []
    assert allowed.calls == ["read-b"]
    assert schedule.executions[0].result.metadata["permission_denied"] is True
    assert schedule.executions[0].result.metadata["permission"] == {
        "outcome": "deny",
        "source": "project_rule",
    }
    assert [execution.index for execution in schedule.executions] == [0, 1]


def test_permission_prompts_are_serial_and_choices_are_call_local(tmp_path: Path) -> None:
    tools = [ControlledTool("read-a"), ControlledTool("read-b")]
    schedule = ToolScheduler(
        _controller(tmp_path), prompt_id_factory=iter(["p1", "p2"]).__next__
    ).schedule(
        "run",
        1,
        [tool_call("1", "read-a"), tool_call("2", "read-b")],
        ToolRegistry(tools),
    )

    async def consume():
        events = []
        async for event in schedule.events():
            events.append(event)
            if isinstance(event, AgentPermissionRequest):
                event.challenge.resolve(
                    PermissionChoice.ONCE
                    if event.challenge.tool_call_id == "1"
                    else PermissionChoice.DENY
                )
        return events

    events = asyncio.run(consume())
    requests = [event for event in events if isinstance(event, AgentPermissionRequest)]
    assert [event.challenge.prompt_id for event in requests] == ["p1", "p2"]
    assert [tool.calls for tool in tools] == [["read-a"], []]


def test_cancel_during_permission_prompt_starts_no_tools(tmp_path: Path) -> None:
    tool = ControlledTool("read-a")
    schedule = ToolScheduler(_controller(tmp_path)).schedule(
        "run", 1, [tool_call("1", "read-a")], ToolRegistry([tool])
    )

    async def consume():
        events = []
        async for event in schedule.events():
            events.append(event)
            if isinstance(event, AgentPermissionRequest):
                await schedule.cancel()
        return events

    events = asyncio.run(asyncio.wait_for(consume(), timeout=1))
    assert tool.calls == []
    results = [event for event in events if isinstance(event, AgentToolResult)]
    assert results[0].execution.result.metadata["cancelled"] is True


def test_permission_denial_returns_to_model_and_agent_loop_continues(
    tmp_path: Path,
) -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call("1", "read-a"))],
            [ProviderTextDelta("used a safer approach")],
        ]
    )
    controller = _controller(tmp_path, [("read-a(test)", "deny")])
    runner = AgentRunner(
        provider,
        ToolScheduler(controller),
        id_factory=lambda: "run",
    )
    events = asyncio.run(
        collect_async(
            runner.start([], "do it", ToolRegistry([ControlledTool("read-a")])).events()
        )
    )
    stopped = next(event for event in events if isinstance(event, AgentStopped))
    assert stopped.reason == StopReason.COMPLETED
    assert len(provider.calls) == 2
    assert provider.calls[1].messages[-1].role == "tool"
    assert "Permission denied" in str(provider.calls[1].messages[-1].content)


def test_e2e_blacklist_and_sandbox_override_allow_mode(tmp_path: Path) -> None:
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    workspace = Workspace(workspace_root)
    rules = (
        parse_permission_rule(
            "run_command(*)", "allow", RuleScope.PROJECT, {"run_command", "read_file"}
        ),
        parse_permission_rule(
            "read_file(**)", "allow", RuleScope.PROJECT, {"run_command", "read_file"}
        ),
    )
    controller = PermissionController(
        PermissionTargetBuilder(workspace),
        PermissionRuleStore(PermissionRuleSets(project=rules), _Writer()),
        PermissionMode.ALLOW,
    )
    command = RunCommandTool(workspace)
    reader = ReadFileTool(workspace)
    schedule = ToolScheduler(controller).schedule(
        "run",
        1,
        [
            tool_call("1", "run_command", command="rm -rf /"),
            tool_call("2", "read_file", path=str(outside)),
        ],
        ToolRegistry([command, reader]),
    )
    events = asyncio.run(collect_async(schedule.events()))
    decisions = [event for event in events if isinstance(event, AgentPermissionDecision)]
    assert [event.source.value for event in decisions] == ["blacklist", "sandbox"]
    assert all(not execution.result.ok for execution in schedule.executions)
    assert outside.read_text(encoding="utf-8") == "secret"


def test_e2e_strict_persistent_rule_requires_session_confirmation(
    tmp_path: Path,
) -> None:
    rule = parse_permission_rule(
        "read-a(test)", "allow", RuleScope.PROJECT_LOCAL, {"read-a"}
    )
    store = PermissionRuleStore(PermissionRuleSets(project_local=(rule,)), _Writer())
    controller = PermissionController(
        PermissionTargetBuilder(Workspace(tmp_path)), store, PermissionMode.STRICT
    )
    call = tool_call("1", "read-a")
    registry = ToolRegistry([ControlledTool("read-a")])

    async def approve_session():
        schedule = ToolScheduler(controller).schedule("run", 1, [call], registry)
        async for event in schedule.events():
            if isinstance(event, AgentPermissionRequest):
                event.challenge.resolve(PermissionChoice.SESSION)
        return schedule

    first = asyncio.run(approve_session())
    assert first.executions[0].result.ok
    second = ToolScheduler(controller).schedule("run", 2, [call], registry)
    second_events = asyncio.run(collect_async(second.events()))
    assert not any(isinstance(event, AgentPermissionRequest) for event in second_events)

    fresh = PermissionController(
        PermissionTargetBuilder(Workspace(tmp_path)),
        PermissionRuleStore(PermissionRuleSets(project_local=(rule,)), _Writer()),
        PermissionMode.STRICT,
    )
    assert fresh.evaluate(registry.validate_call(call)).outcome == PermissionOutcome.ASK
