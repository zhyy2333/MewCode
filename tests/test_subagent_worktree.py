from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.context import ContextConfig
from mewcode.permissions import PermissionMode, PermissionRuleSets
from mewcode.prompting import PromptAdditions, PromptBuilder, PromptEnvironmentProvider
from mewcode.providers import ProviderTextDelta, RequestBoundaryProvider
from mewcode.subagents import (
    AgentDefinition,
    AgentDefinitionLayer,
    AgentDefinitionSource,
    AgentIsolation,
    FrozenSubagentToolPolicy,
    SubagentKind,
    SubagentLaunch,
    SubagentParent,
    SubagentPlacement,
    SubagentRuntimeFactory,
    SubagentTaskStatus,
    WorkspaceRuntimeBundleFactory,
    WorktreeSubagentDriver,
)
from mewcode.tools import ToolRegistry, ToolSafety, Workspace, create_builtin_registry
from mewcode.worktrees import WorktreeConfigLoader, WorktreeLifecycleService
from tests.fakes import ScriptedAsyncProvider, collect_async
from tests.worktrees.helpers import repository


def test_worktree_driver_starts_model_after_ready_and_cleans(tmp_path: Path) -> None:
    root = repository(tmp_path)
    inner = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    provider = RequestBoundaryProvider(inner)
    runtime_factory = SubagentRuntimeFactory(
        provider_supplier=lambda _name: provider,
        prompt_builder=PromptBuilder(PromptEnvironmentProvider(root)),
        workspace=Workspace(root),
        hook_runtime=None,
        context_config_factory=lambda _name: ContextConfig(128_000),
    )
    source = AgentDefinitionSource(
        AgentDefinitionLayer.PROJECT,
        root,
        root / "coder.md",
        "coder",
        "test",
    )
    definition = AgentDefinition(
        "coder",
        "code",
        ("read_file",),
        (),
        "inherit",
        4,
        PermissionMode.DEFAULT,
        "Work only in the isolated Worktree.",
        source,
        AgentIsolation.WORKTREE,
    )
    tools = create_builtin_registry(Workspace(root)).select_names(("read_file",))
    holder = {}
    launch = SubagentLaunch(
        SubagentKind.DEFINED,
        "coder",
        "main",
        SubagentParent("parent", 1),
        SubagentPlacement.FOREGROUND,
        lambda task_id: holder["driver"],
        task_text="inspect tracked.txt",
        definition=definition,
        tools=tools,
        policy=FrozenSubagentToolPolicy(frozenset({"read_file"}), {}),
        permission_rules=PermissionRuleSets(),
        permission_mode=PermissionMode.DEFAULT,
        allowed_safety=frozenset({ToolSafety.READ_ONLY}),
        additions=PromptAdditions(custom_instructions="user instruction"),
    )
    lifecycle = WorktreeLifecycleService(
        root,
        WorktreeConfigLoader().load(root / ".mewcode" / "worktrees.yaml"),
    )
    driver = WorktreeSubagentDriver(
        "01234567-89ab-cdef-0123-456789abcdef",
        launch,
        lifecycle,
        WorkspaceRuntimeBundleFactory(runtime_factory),
    )
    holder["driver"] = driver

    async def scenario() -> None:
        await collect_async(driver.events())
        assert driver.outcome.status is SubagentTaskStatus.COMPLETED
        assert inner.calls
        assert ".mewcode\\worktrees" in inner.calls[0].prompt.dynamic_system or ".mewcode/worktrees" in inner.calls[0].prompt.dynamic_system
        await driver.close()
        assert driver.outcome.worktree is not None
        assert driver.outcome.worktree.state == "deleted"

    asyncio.run(scenario())
