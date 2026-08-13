from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.agent import AgentControlContext, AgentMode
from mewcode.permissions import (
    PermissionMode,
    PermissionRuleSets,
    PermissionRuleStore,
)
from mewcode.prompting import PromptAdditions, PromptPackage
from mewcode.providers import ModelRequest
from mewcode.subagents import (
    AGENT_TOOL_SCHEMA,
    AgentDefinition,
    AgentDefinitionCatalog,
    AgentDefinitionLayer,
    AgentDefinitionSource,
    AgentTool,
    SubagentCoordinator,
    SubagentDriverOutcome,
    SubagentKind,
    SubagentPlacement,
    SubagentProgress,
    SubagentTaskManager,
    SubagentTaskStatus,
)
from mewcode.tools import ToolRegistry, ToolSafety
from tests.fakes import ControlledTool, collect_async


class Writer:
    def add_local_allow(self, target):
        raise AssertionError("not expected")


class FakeRuntimeFactory:
    def __init__(self, driver_factory=None):
        self.driver_factory = driver_factory or (lambda: FakeDriver())
        self.calls = []

    def create(self, task_id, launch):
        self.calls.append((task_id, launch))
        return self.driver_factory()


class FakeDriver:
    def __init__(self, *, gate=None, status=SubagentTaskStatus.COMPLETED):
        self.gate = gate
        self._outcome = SubagentDriverOutcome(status, "final", "failed" if status is SubagentTaskStatus.FAILED else None)
        self.cancel_calls = 0
        self.close_calls = 0

    async def events(self):
        yield SubagentProgress(1, "working", "bounded progress")
        if self.gate is not None:
            await self.gate.wait()

    @property
    def outcome(self):
        return self._outcome

    async def cancel(self):
        self.cancel_calls += 1
        self._outcome = SubagentDriverOutcome(SubagentTaskStatus.CANCELLED, error="cancelled")
        if self.gate is not None:
            self.gate.set()

    async def close(self):
        self.close_calls += 1


def _definition(tmp_path: Path, *, model="inherit"):
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
        ("read",),
        (),
        model,
        5,
        PermissionMode.DEFAULT,
        "role body",
        source,
    )


def _context(registry: ToolRegistry):
    request = ModelRequest(PromptPackage("stable", "dynamic"), (), registry, 2222)
    return AgentControlContext(
        "parent",
        3,
        AgentMode.DIRECT,
        "main",
        PermissionMode.DEFAULT,
        7,
        frozenset({ToolSafety.READ_ONLY}),
        request,
    )


def _coordinator(tmp_path, runtime_factory, *, definitions=None, additions=None):
    read = ControlledTool("read")
    agent = ControlledTool("agent")
    registry = ToolRegistry([read, agent])
    catalog = AgentDefinitionCatalog(
        definitions if definitions is not None else {"reviewer": _definition(tmp_path)}
    )
    store = PermissionRuleStore(PermissionRuleSets(), Writer())
    coordinator = SubagentCoordinator(
        catalog,
        runtime_factory,
        registry,
        store,
        background_capable_names={"read", "agent"},
        additions_supplier=lambda: additions or PromptAdditions(),
    )
    return coordinator, registry


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"type": "other", "task": "x"},
        {"type": "defined", "task": " " , "role": "reviewer"},
        {"type": "defined", "task": "x"},
        {"type": "defined", "task": "x", "role": " "},
        {"type": "defined", "task": "x", "role": "missing"},
        {"type": "defined", "task": "x", "role": "reviewer", "background": "yes"},
        {"type": "fork", "task": "x", "role": "reviewer"},
        {"type": "fork", "task": "x", "background": False},
        {"type": "fork", "task": "x", "extra": 1},
    ],
)
def test_prepare_rejects_invalid_arguments_before_runtime(tmp_path: Path, arguments) -> None:
    runtime = FakeRuntimeFactory()
    coordinator, registry = _coordinator(tmp_path, runtime)
    with pytest.raises(ValueError):
        coordinator.prepare(arguments, _context(registry))
    assert runtime.calls == []


def test_prepare_requires_actual_request_context_and_task_byte_limit(tmp_path: Path) -> None:
    runtime = FakeRuntimeFactory()
    coordinator, registry = _coordinator(tmp_path, runtime)
    with pytest.raises(ValueError, match="parent request"):
        coordinator.prepare({"type": "defined", "task": "x", "role": "reviewer"}, None)
    with pytest.raises(ValueError, match="65536"):
        coordinator.prepare(
            {"type": "defined", "task": "😀" * 20_000, "role": "reviewer"},
            _context(registry),
        )


def test_defined_and_fork_launches_freeze_profile_placement_and_policy(tmp_path: Path) -> None:
    runtime = FakeRuntimeFactory()
    additions = PromptAdditions(custom_instructions="custom", active_skills="omit")
    coordinator, registry = _coordinator(tmp_path, runtime, additions=additions)
    context = _context(registry)

    defined = coordinator.prepare(
        {"type": "defined", "task": " review ", "role": "reviewer"},
        context,
    )
    fork = coordinator.prepare({"type": "fork", "task": "continue"}, context)

    assert defined.kind is SubagentKind.DEFINED
    assert defined.task_text == "review"
    assert defined.profile_name == "main"
    assert defined.placement is SubagentPlacement.FOREGROUND
    assert defined.tools.names == ("read",)
    assert defined.policy.executable_names == frozenset({"read"})
    assert defined.permission_rules.session == ()
    assert defined.additions.custom_instructions == "custom"
    assert defined.additions.active_skills is None
    assert fork.kind is SubagentKind.FORK
    assert fork.placement is SubagentPlacement.BACKGROUND
    assert fork.seed.request is context.parent_request
    assert fork.seed.max_iterations == 7
    assert fork.tools is context.parent_request.tools
    assert "agent" not in fork.policy.executable_names


def test_agent_tool_schema_is_stable_across_catalog_and_task_state(tmp_path: Path) -> None:
    runtime = FakeRuntimeFactory()
    coordinator, _ = _coordinator(tmp_path, runtime)
    manager = SubagentTaskManager()
    first = AgentTool(coordinator, manager)
    second = AgentTool(coordinator, manager)
    assert first.name == second.name == "agent"
    assert first.description == second.description
    assert first.parameters_schema is second.parameters_schema is AGENT_TOOL_SCHEMA
    assert AGENT_TOOL_SCHEMA == {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["defined", "fork"]},
            "task": {"type": "string"},
            "role": {"type": "string"},
            "background": {"type": "boolean"},
        },
        "required": ["type", "task"],
        "additionalProperties": False,
    }


def test_explicit_background_and_fork_return_before_blocked_driver(tmp_path: Path) -> None:
    async def scenario(kind):
        gate = asyncio.Event()
        runtime = FakeRuntimeFactory(lambda: FakeDriver(gate=gate))
        coordinator, registry = _coordinator(tmp_path, runtime)
        manager = SubagentTaskManager(id_factory=lambda: f"{kind}-task")
        tool = AgentTool(coordinator, manager)
        arguments = (
            {"type": "defined", "task": "x", "role": "reviewer", "background": True}
            if kind == "defined"
            else {"type": "fork", "task": "x"}
        )
        operation = tool.control_operation(arguments, _context(registry))
        events = await collect_async(operation.events())
        result = operation.result
        snapshot = manager.get(f"{kind}-task")
        gate.set()
        await asyncio.sleep(0)
        await manager.close()
        return events, result, snapshot

    for kind in ("defined", "fork"):
        events, result, snapshot = asyncio.run(scenario(kind))
        assert events == []
        assert result.ok is True
        assert result.metadata["placement"] == "background"
        assert snapshot.status.active


def test_foreground_returns_only_bounded_progress_and_final_result(tmp_path: Path) -> None:
    async def scenario(status):
        runtime = FakeRuntimeFactory(lambda: FakeDriver(status=status))
        coordinator, registry = _coordinator(tmp_path, runtime)
        manager = SubagentTaskManager(id_factory=lambda: "task")
        operation = AgentTool(coordinator, manager).control_operation(
            {"type": "defined", "task": "x", "role": "reviewer"},
            _context(registry),
        )
        events = await collect_async(operation.events())
        result = operation.result
        await manager.close()
        return events, result

    events, result = asyncio.run(scenario(SubagentTaskStatus.COMPLETED))
    assert all(type(event).__name__ == "AgentSubagentProgress" for event in events)
    assert result.ok and result.content == "final"
    _, failed = asyncio.run(scenario(SubagentTaskStatus.FAILED))
    assert not failed.ok and failed.error == "failed"


def test_operation_cancel_only_owns_foreground_task(tmp_path: Path) -> None:
    async def scenario():
        gate = asyncio.Event()
        driver = FakeDriver(gate=gate)
        runtime = FakeRuntimeFactory(lambda: driver)
        coordinator, registry = _coordinator(tmp_path, runtime)
        manager = SubagentTaskManager(id_factory=lambda: "task")
        operation = AgentTool(coordinator, manager).control_operation(
            {"type": "defined", "task": "x", "role": "reviewer"},
            _context(registry),
        )
        consumer = asyncio.create_task(collect_async(operation.events()))
        for _ in range(5):
            await asyncio.sleep(0)
        await operation.cancel()
        await consumer
        await manager.close()
        return driver.cancel_calls, operation.result

    cancel_calls, result = asyncio.run(scenario())
    assert cancel_calls == 1
    assert result.ok is False
    assert result.metadata["status"] == "cancelled"
