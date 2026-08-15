from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.agent import ForkRequestSeed
from mewcode.context import ContextConfig
from mewcode.permissions import PermissionMode, PermissionRuleSets
from mewcode.prompting import (
    PromptAdditions,
    PromptBuilder,
    PromptEnvironmentProvider,
    PromptPackage,
)
from mewcode.providers import (
    ChatMessage,
    ModelRequest,
    ProviderTextDelta,
    ProviderToolCall,
    RequestBoundaryProvider,
    TokenUsage,
)
from mewcode.subagents import (
    AgentDefinition,
    AgentDefinitionLayer,
    AgentDefinitionSource,
    FrozenSubagentToolPolicy,
    SubagentKind,
    SubagentLaunch,
    SubagentParent,
    SubagentPlacement,
    SubagentRuntimeFactory,
    SubagentTaskStatus,
)
from mewcode.tools import ToolRegistry, ToolSafety, Workspace
from tests.fakes import ControlledTool, ScriptedAsyncProvider, collect_async, tool_call


def _definition(tmp_path: Path, *, tools=(), max_turns=4):
    source = AgentDefinitionSource(
        AgentDefinitionLayer.PROJECT,
        tmp_path,
        tmp_path / "reviewer.md",
        "reviewer",
        "project",
    )
    return AgentDefinition(
        "reviewer",
        "review",
        tuple(tools),
        (),
        "inherit",
        max_turns,
        PermissionMode.DEFAULT,
        "You are the independent reviewer.",
        source,
    )


def _factory(tmp_path: Path, provider):
    return SubagentRuntimeFactory(
        provider_supplier=lambda profile: provider,
        prompt_builder=PromptBuilder(PromptEnvironmentProvider(tmp_path)),
        workspace=Workspace(tmp_path),
        hook_runtime=None,
        context_config_factory=lambda profile: ContextConfig(128_000),
    )


def _defined_launch(tmp_path: Path, factory, *, tools=None, additions=None):
    definition = _definition(tmp_path, tools=(tools.names if tools else ()))
    policy = FrozenSubagentToolPolicy(
        frozenset(tools.names if tools else ()), {}
    )
    holder = {}

    def create(task_id):
        return factory.create(task_id, holder["launch"])

    launch = SubagentLaunch(
        SubagentKind.DEFINED,
        "reviewer",
        "main",
        SubagentParent("parent", 1),
        SubagentPlacement.FOREGROUND,
        create,
        task_text="review this change",
        definition=definition,
        tools=tools or ToolRegistry([]),
        policy=policy,
        permission_rules=PermissionRuleSets(),
        permission_mode=PermissionMode.DEFAULT,
        allowed_safety=frozenset({ToolSafety.READ_ONLY}),
        additions=additions or PromptAdditions(),
    )
    holder["launch"] = launch
    return launch


def test_factory_isolates_mutable_runtime_state_but_shares_infrastructure(
    tmp_path: Path,
) -> None:
    inner = ScriptedAsyncProvider([[ProviderTextDelta("one")], [ProviderTextDelta("two")]])
    provider = RequestBoundaryProvider(inner)
    factory = _factory(tmp_path, provider)
    launch = _defined_launch(tmp_path, factory)

    first = factory.create("one", launch)
    second = factory.create("two", launch)

    assert first is not second
    assert first.context_manager is not second.context_manager
    assert first.observations is not second.observations
    assert first.permissions is not second.permissions
    assert first.scheduler is not second.scheduler
    assert first.provider is second.provider is provider
    assert first.workspace is second.workspace is factory.workspace
    asyncio.run(first.close())
    asyncio.run(second.close())


def test_defined_runtime_starts_blank_and_sanitizes_dynamic_additions(
    tmp_path: Path,
) -> None:
    inner = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    provider = RequestBoundaryProvider(inner)
    factory = _factory(tmp_path, provider)
    additions = PromptAdditions(
        custom_instructions="project instructions",
        long_term_memory="remember this",
        available_skills="must disappear",
        active_skills="must disappear too",
        agent_role="parent role",
    )
    runtime = factory.create(
        "task",
        _defined_launch(tmp_path, factory, additions=additions),
    )

    asyncio.run(collect_async(runtime.events()))
    request = inner.calls[0]
    assert request.messages == (ChatMessage("user", "review this change"),)
    assert "## Agent Role\nYou are the independent reviewer." in request.prompt.dynamic_system
    assert "project instructions" in request.prompt.dynamic_system
    assert "remember this" in request.prompt.dynamic_system
    assert "must disappear" not in request.prompt.dynamic_system
    assert "parent role" not in request.prompt.dynamic_system
    assert runtime.outcome.status is SubagentTaskStatus.COMPLETED
    assert runtime.run.outcome.committed_history == runtime.run.outcome.new_messages
    asyncio.run(runtime.close())
    assert not (tmp_path / ".mewcode" / "context" / "subagent-task").exists()


def test_defined_runtime_uses_frozen_tool_view_and_task_usage(tmp_path: Path) -> None:
    read = ControlledTool("read")
    tools = ToolRegistry([read])
    inner = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    provider = RequestBoundaryProvider(inner)
    factory = _factory(tmp_path, provider)
    runtime = factory.create("task", _defined_launch(tmp_path, factory, tools=tools))
    asyncio.run(collect_async(runtime.events()))

    assert inner.calls[0].tools.names == ("read",)
    assert runtime.outcome.status is SubagentTaskStatus.COMPLETED
    asyncio.run(runtime.close())


def test_subagent_runtime_stops_after_three_noninteractive_denials(
    tmp_path: Path,
) -> None:
    read = ControlledTool("read")
    tools = ToolRegistry([read])
    inner = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call(str(index), "read"))]
            for index in range(3)
        ]
    )
    provider = RequestBoundaryProvider(inner)
    factory = _factory(tmp_path, provider)
    runtime = factory.create(
        "denied-task",
        _defined_launch(tmp_path, factory, tools=tools),
    )

    asyncio.run(collect_async(runtime.events()))

    assert len(inner.calls) == 3
    assert read.calls == []
    assert runtime.outcome.status is SubagentTaskStatus.FAILED
    assert runtime.outcome.error == (
        "All tool calls were denied for 3 consecutive iterations."
    )
    asyncio.run(runtime.close())


def test_fork_runtime_preserves_parent_first_request_and_is_independent(
    tmp_path: Path,
) -> None:
    parent_tools = ToolRegistry([ControlledTool("read"), ControlledTool("agent")])
    parent = ModelRequest(
        PromptPackage("stable-parent", "dynamic-parent"),
        (ChatMessage("user", "old"), ChatMessage("assistant", "answer")),
        parent_tools,
        1234,
    )
    seed = ForkRequestSeed(
        "main",
        parent,
        "parent-run",
        2,
        PermissionMode.DEFAULT,
        3,
        frozenset({ToolSafety.READ_ONLY}),
    )
    inner = ScriptedAsyncProvider([[ProviderTextDelta("fork done")]])
    provider = RequestBoundaryProvider(inner)
    factory = _factory(tmp_path, provider)
    policy = FrozenSubagentToolPolicy(frozenset({"read"}), {"agent": "forbidden"})
    holder = {}

    def create(task_id):
        return factory.create(task_id, holder["launch"])

    launch = SubagentLaunch(
        SubagentKind.FORK,
        None,
        "main",
        SubagentParent("parent-run", 2),
        SubagentPlacement.BACKGROUND,
        create,
        task_text="new fork task",
        tools=parent_tools,
        policy=policy,
        permission_rules=PermissionRuleSets(),
        permission_mode=PermissionMode.DEFAULT,
        allowed_safety=frozenset({ToolSafety.READ_ONLY}),
        seed=seed,
    )
    holder["launch"] = launch
    runtime = factory.create("fork", launch)
    asyncio.run(collect_async(runtime.events()))

    request = inner.calls[0]
    assert request.prompt is parent.prompt
    assert request.messages == parent.messages + (ChatMessage("user", "new fork task"),)
    assert request.tools is parent.tools
    assert request.max_output_tokens == 1234
    assert runtime.outcome.result == "fork done"
    asyncio.run(runtime.close())


def test_runtime_close_is_idempotent_and_does_not_close_shared_provider(
    tmp_path: Path,
) -> None:
    inner = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    provider = RequestBoundaryProvider(inner)
    factory = _factory(tmp_path, provider)
    runtime = factory.create("task", _defined_launch(tmp_path, factory))
    asyncio.run(collect_async(runtime.events()))
    asyncio.run(runtime.close())
    asyncio.run(runtime.close())
    assert inner.calls
