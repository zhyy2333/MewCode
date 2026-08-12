from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.agent import AgentRunner, ToolScheduler
from mewcode.conversation import Conversation
from mewcode.providers import ProviderTextDelta
from mewcode.skills import (
    LoadSkillTool,
    SkillCoordinator,
    SkillRoots,
    SkillRuntime,
    build_skill_catalog,
    discover_sources,
)
from mewcode.tools import ToolRegistry
from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider, collect_async


def _write(root: Path, name: str, mode: str, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    history = "\nhistory: 0" if mode == "isolated" else ""
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}\ntools: []\nmode: {mode}{history}\n---\n{body}",
        encoding="utf-8",
    )


def _runner(provider):
    return AgentRunner(provider, ToolScheduler(AllowAllPermissionController()))


def _system(tmp_path: Path, main_provider, child_provider):
    roots = SkillRoots(tmp_path / "skills", tmp_path / "user", tmp_path / "builtin")
    _write(roots.project, "shared", "shared", "Shared {{input}}")
    _write(roots.project, "private", "isolated", "Private {{input}}")
    catalog = build_skill_catalog(discover_sources(roots), global_tool_names=set())
    runtime = SkillRuntime(catalog, tmp_path, ToolRegistry([]))
    conversation_ref = {}
    coordinator = SkillCoordinator(
        runtime,
        runner_factory=lambda profile: _runner(child_provider),
        history_supplier=lambda: conversation_ref["value"].messages(),
        base_additions_supplier=lambda: conversation_ref["value"].skill_base_additions(),
        allowed_safety_supplier=lambda: conversation_ref["value"].current_skill_safety(),
    )
    loader = LoadSkillTool(coordinator)
    registry = ToolRegistry([loader])
    runtime.set_global_tools(registry)
    conversation = Conversation(
        _runner(main_provider),
        registry,
        skill_runtime=runtime,
        skill_coordinator=coordinator,
    )
    conversation_ref["value"] = conversation
    return conversation, runtime


def test_direct_shared_skill_preserves_raw_slash_and_normal_history(tmp_path: Path) -> None:
    main = ScriptedAsyncProvider([[ProviderTextDelta("shared answer")]])
    conversation, runtime = _system(tmp_path, main, ScriptedAsyncProvider([]))
    asyncio.run(
        collect_async(conversation.invoke_skill("shared", "Keep CASE", "/Shared Keep CASE"))
    )
    messages = conversation.messages()
    assert messages[0].content == "/Shared Keep CASE"
    assert messages[-1].content["text"] == "shared answer"
    assert "Shared Keep CASE" in main.calls[0].prompt.dynamic_system
    assert [item.name for item in runtime.active] == ["shared"]


def test_direct_isolated_skill_folds_only_command_and_final_reply(tmp_path: Path) -> None:
    child = ScriptedAsyncProvider([[ProviderTextDelta("isolated answer")]])
    conversation, runtime = _system(tmp_path, ScriptedAsyncProvider([]), child)
    asyncio.run(
        collect_async(conversation.invoke_skill("private", "focus", "/private focus"))
    )
    messages = conversation.messages()
    assert [(item.role, item.content) for item in messages] == [
        ("user", "/private focus"),
        ("assistant", "isolated answer"),
    ]
    assert "Private focus" in child.calls[0].prompt.dynamic_system
    assert [item.name for item in runtime.active] == ["private"]


def test_reset_clears_messages_and_all_skill_activations(tmp_path: Path) -> None:
    main = ScriptedAsyncProvider([[ProviderTextDelta("answer")]])
    conversation, runtime = _system(tmp_path, main, ScriptedAsyncProvider([]))
    asyncio.run(collect_async(conversation.invoke_skill("shared", "x", "/shared x")))
    assert conversation.messages() and runtime.active
    asyncio.run(conversation.reset())
    assert conversation.messages() == []
    assert runtime.active == ()
