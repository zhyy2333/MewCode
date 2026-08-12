from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mewcode.agent import AgentRunner, ToolScheduler
from mewcode.prompting import PromptAdditions
from mewcode.providers import ProviderTextDelta, ProviderToolCall
from mewcode.providers import MessageKind
from mewcode.skills import (
    LoadSkillTool,
    SkillCoordinator,
    SkillRoots,
    SkillRuntime,
    build_skill_catalog,
    discover_sources,
)
from mewcode.tools import (
    PermissionTargetKind,
    ToolCallRequest,
    ToolPermissionSpec,
    ToolRegistry,
    ToolResult,
    ToolSafety,
)
from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider, collect_async


def _skill(root: Path, name: str, mode: str, body: str, tools: str = "[]") -> None:
    root.mkdir(parents=True, exist_ok=True)
    history = "\nhistory: 0" if mode == "isolated" else ""
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}\ntools: {tools}\nmode: {mode}{history}\n---\n{body}",
        encoding="utf-8",
    )


def _runtime(tmp_path: Path) -> SkillRuntime:
    roots = SkillRoots(tmp_path / "skills", tmp_path / "user", tmp_path / "builtin")
    _skill(roots.project, "shared", "shared", "Shared {{input}}")
    _skill(roots.project, "private", "isolated", "Private {{input}}")
    catalog = build_skill_catalog(discover_sources(roots), global_tool_names=set())
    return SkillRuntime(catalog, tmp_path, ToolRegistry([]))


def _runner(provider, controller=None):
    return AgentRunner(
        provider, ToolScheduler(controller or AllowAllPermissionController())
    )


class RejectEvaluationController:
    def evaluate(self, call):
        raise AssertionError("load_skill must not request its own permission")


class NamedTool:
    description = "Named test tool."
    parameters_schema = {"type": "object", "properties": {}}
    permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL)

    def __init__(self, name: str, safety: ToolSafety) -> None:
        self.name = name
        self.safety = safety

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(True, self.name, "ok")


def test_shared_load_tool_activates_and_next_parent_iteration_sees_sop(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    child_provider = ScriptedAsyncProvider([])
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(child_provider),
        history_supplier=lambda: (),
    )
    loader = LoadSkillTool(coordinator)
    runtime.set_global_tools(ToolRegistry([loader]))
    parent = ScriptedAsyncProvider(
        [
            [
                ProviderToolCall(
                    ToolCallRequest(
                        "1",
                        "load_skill",
                        {"name": "shared", "input": "focus"},
                        '{"name":"shared","input":"focus"}',
                    )
                )
            ],
            [ProviderTextDelta("done")],
        ]
    )
    run = _runner(parent, RejectEvaluationController()).start(
        [],
        "work",
        ToolRegistry([loader]),
        run_view_provider=lambda: runtime.run_view(
            {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
        ),
    )
    asyncio.run(collect_async(run.events()))
    assert run.outcome.completed
    assert "Shared focus" not in parent.calls[0].prompt.dynamic_system
    assert "Shared focus" in parent.calls[1].prompt.dynamic_system
    assert [item.name for item in runtime.active] == ["shared"]


def test_agent_isolated_call_persists_only_paired_parent_tool_messages(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    child = ScriptedAsyncProvider([[ProviderTextDelta("private final")]])
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(child),
        history_supplier=lambda: (),
    )
    loader = LoadSkillTool(coordinator)
    runtime.set_global_tools(ToolRegistry([loader]))
    parent = ScriptedAsyncProvider(
        [
            [
                ProviderToolCall(
                    ToolCallRequest(
                        "private-1",
                        "load_skill",
                        {"name": "private", "input": "focus"},
                        '{"name":"private","input":"focus"}',
                    )
                )
            ],
            [ProviderTextDelta("parent final")],
        ]
    )
    run = _runner(parent).start(
        [],
        "review privately",
        ToolRegistry([loader]),
        run_view_provider=lambda: runtime.run_view(
            {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
        ),
    )
    asyncio.run(collect_async(run.events()))

    messages = run.outcome.committed_history
    assert [message.kind for message in messages] == [
        MessageKind.USER,
        MessageKind.TOOL_CALL,
        MessageKind.TOOL_RESULT,
        MessageKind.ASSISTANT,
    ]
    assert messages[2].content[0]["content"] == "private final"
    assert all("Private focus" not in str(message.content) for message in messages)
    assert len(child.calls) == 1


def test_isolated_invocation_returns_final_reply_without_child_history_persistence(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    child = ScriptedAsyncProvider([[ProviderTextDelta("isolated result")]])
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(child),
        history_supplier=lambda: (),
        base_additions_supplier=lambda: PromptAdditions(custom_instructions="instructions"),
    )
    loader = LoadSkillTool(coordinator)
    runtime.set_global_tools(ToolRegistry([loader]))
    operation = coordinator.invoke("private", "focus")
    asyncio.run(collect_async(operation.events()))
    assert operation.result.ok
    assert operation.result.content == "isolated result"
    assert len(child.calls) == 1
    assert "Private focus" in child.calls[0].prompt.dynamic_system
    assert "instructions" in child.calls[0].prompt.dynamic_system


def test_isolated_final_reply_is_bounded_before_parent_tool_result(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    child = ScriptedAsyncProvider([[ProviderTextDelta("x" * 25_000)]])
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(child),
        history_supplier=lambda: (),
    )
    operation = coordinator.invoke("private")
    asyncio.run(collect_async(operation.events()))
    assert operation.result.ok
    assert len(operation.result.content) < 25_000
    assert operation.result.metadata == {"truncated": True}


def test_run_view_uses_shared_union_plus_current_isolated_and_safety(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(ScriptedAsyncProvider([])),
        history_supplier=lambda: (),
    )
    loader = LoadSkillTool(coordinator)
    runtime.set_global_tools(ToolRegistry([loader]))
    runtime.activate("shared")
    runtime.activate("private")
    main = runtime.run_view({ToolSafety.READ_ONLY})
    isolated = runtime.run_view({ToolSafety.READ_ONLY}, isolated_name="private")
    assert main.tools.names == ("load_skill",)
    assert isolated.tools.names == ("load_skill",)
    assert "Private" not in main.additions.active_skills
    assert "Private" in isolated.additions.active_skills


def test_run_view_whitelist_union_and_mode_intersection(tmp_path: Path) -> None:
    roots = SkillRoots(tmp_path / "skills", tmp_path / "user", tmp_path / "builtin")
    _skill(roots.project, "first", "shared", "First", "[read-one]")
    _skill(roots.project, "second", "shared", "Second", "[write-two]")
    _skill(roots.project, "private", "isolated", "Private", "[write-three]")
    names = {"read-one", "write-two", "write-three"}
    catalog = build_skill_catalog(discover_sources(roots), global_tool_names=names)
    runtime = SkillRuntime(catalog, tmp_path, ToolRegistry([]))
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(ScriptedAsyncProvider([])),
        history_supplier=lambda: (),
    )
    loader = LoadSkillTool(coordinator)
    runtime.set_global_tools(
        ToolRegistry(
            [
                NamedTool("read-one", ToolSafety.READ_ONLY),
                NamedTool("write-two", ToolSafety.SIDE_EFFECT),
                NamedTool("write-three", ToolSafety.SIDE_EFFECT),
                loader,
            ]
        )
    )

    all_safety = {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
    assert runtime.run_view(all_safety).tools.names == (
        "read-one", "write-two", "write-three", "load_skill"
    )
    runtime.activate("first")
    runtime.activate("second")
    assert runtime.run_view(all_safety).tools.names == (
        "read-one", "write-two", "load_skill"
    )
    assert runtime.run_view({ToolSafety.READ_ONLY}).tools.names == (
        "read-one", "load_skill"
    )
    runtime.activate("private")
    assert runtime.run_view(all_safety, isolated_name="private").tools.names == (
        "read-one", "write-two", "write-three", "load_skill"
    )


def test_isolated_nesting_depth_is_bounded(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(ScriptedAsyncProvider([])),
        history_supplier=lambda: (),
        depth=4,
    )
    operation = coordinator.invoke("private")
    asyncio.run(collect_async(operation.events()))
    assert not operation.result.ok
    assert "4 levels" in (operation.result.error or "")
