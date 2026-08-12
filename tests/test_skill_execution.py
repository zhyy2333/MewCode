from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.agent import AgentRunner, ToolScheduler
from mewcode.prompting import PromptAdditions
from mewcode.providers import ProviderTextDelta, ProviderToolCall
from mewcode.skills import (
    LoadSkillTool,
    SkillCoordinator,
    SkillRoots,
    SkillRuntime,
    build_skill_catalog,
    discover_sources,
)
from mewcode.tools import ToolCallRequest, ToolRegistry, ToolSafety
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
