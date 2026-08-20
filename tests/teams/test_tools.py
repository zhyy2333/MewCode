from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from mewcode.tools import (
    PermissionTargetKind,
    ToolPermissionSpec,
    ToolRegistry,
    ToolResult,
    ToolSafety,
)
from mewcode.agent import AgentControlContext, AgentMode, AgentRunView
from mewcode.permissions import PermissionMode
from mewcode.prompting import PromptPackage
from mewcode.providers import ModelRequest
from mewcode.teams.coordinator import TeamRunViewComposer
from mewcode.teams.tools import (
    TEAM_MEMBER_SCHEMA,
    TEAM_MESSAGE_SCHEMA,
    TEAM_SCHEMA,
    TEAM_TASK_SCHEMA,
    TeamLifecycleTool,
    TeamMessageTool,
    TeamTaskTool,
)
from mewcode.teams.policy import ApprovalGuardedTool, build_member_tool_scope

from .helpers import FakeClock, actor, role, state_with_members


class _Tool:
    description = "test"
    parameters_schema = {"type": "object", "properties": {}}
    permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL, "test")

    def __init__(self, name: str, safety: ToolSafety = ToolSafety.READ_ONLY) -> None:
        self.name = name
        self.safety = safety
        self.calls = 0

    async def execute(self, arguments):
        del arguments
        self.calls += 1
        return ToolResult(True, self.name, "ok")


def test_member_scope_is_narrowed_and_control_tools_cannot_be_restored(tmp_path) -> None:
    snapshot = role()
    base = ToolRegistry(
        (
            _Tool("read_file"),
            _Tool("write_file", ToolSafety.SIDE_EFFECT),
            _Tool("agent"),
            _Tool("load_skill"),
            _Tool("team"),
            _Tool("team_member"),
        )
    )
    collaboration = ToolRegistry((_Tool("team_task"), _Tool("team_message"), _Tool("team_member")))

    scope = build_member_tool_scope(
        base,
        snapshot,
        collaboration_registry=collaboration,
        workspace_allowed_names=base.names,
    )

    assert set(scope.registry.names) == {"read_file", "write_file", "team_task", "team_message"}
    assert not {"agent", "load_skill", "team", "team_member"}.intersection(scope.registry.names)


class _Approvals:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    @asynccontextmanager
    async def side_effect_permit(self, actor, task_id):
        del actor, task_id
        if not self.allowed:
            from mewcode.teams.models import TeamPermissionError

            raise TeamPermissionError("not approved")
        yield object()


def test_approval_guarded_tool_rechecks_before_side_effect(tmp_path) -> None:
    state = state_with_members(tmp_path, 1, FakeClock())
    inner = _Tool("write_file", ToolSafety.SIDE_EFFECT)
    denied = ApprovalGuardedTool(
        inner,
        _Approvals(False),
        actor(state, "member-1"),
        lambda: "task-1",
    )
    denied_result = asyncio.run(denied.execute({}))
    assert not denied_result.ok
    assert denied_result.metadata["approval_required"]
    assert inner.calls == 0

    allowed = ApprovalGuardedTool(
        inner,
        _Approvals(True),
        actor(state, "member-1"),
        lambda: "task-1",
    )
    assert asyncio.run(allowed.execute({})).ok
    assert inner.calls == 1


def test_team_tool_schemas_are_fixed_and_do_not_embed_runtime_names() -> None:
    encoded = [
        __import__("json").dumps(item, sort_keys=True)
        for item in (TEAM_SCHEMA, TEAM_MEMBER_SCHEMA, TEAM_TASK_SCHEMA, TEAM_MESSAGE_SCHEMA)
    ]
    assert len(set(encoded)) == 4
    assert all("member-1" not in item and "task-1" not in item for item in encoded)
    assert [TEAM_SCHEMA["required"], TEAM_MEMBER_SCHEMA["required"]] == [["action"], ["action"]]


class _LifecycleCoordinator:
    def list(self):
        return ()


def _control_context(mode):
    registry = ToolRegistry([])
    request = ModelRequest(PromptPackage("stable", "dynamic"), (), registry, 100)
    return AgentControlContext(
        "run",
        1,
        mode,
        "main",
        PermissionMode.DEFAULT,
        5,
        frozenset({ToolSafety.READ_ONLY}),
        request,
    )


def test_team_lifecycle_schema_errors_and_plan_gate_are_stable() -> None:
    async def invoke(arguments, mode):
        tool = TeamLifecycleTool(_LifecycleCoordinator(), root_session_id=lambda: "root")
        operation = tool.control_operation(arguments, _control_context(mode))
        async for _ in operation.events():
            pass
        return operation.result

    unknown = asyncio.run(invoke({"action": "unknown"}, AgentMode.DIRECT))
    assert not unknown.ok
    assert "Unknown or missing" in unknown.error
    denied = asyncio.run(invoke({"action": "detach"}, AgentMode.PLAN))
    assert not denied.ok
    assert "PLAN mode" in denied.error
    assert asyncio.run(invoke({"action": "list"}, AgentMode.PLAN)).ok


def test_root_run_view_adds_and_removes_lead_tools_without_restart() -> None:
    lifecycle = ToolRegistry((_Tool("team"),))
    lead = ToolRegistry((_Tool("team_member"), _Tool("team_task"), _Tool("team_message")))

    class Coordinator:
        attached = False

        def active_attachment(self):
            if not self.attached:
                return None
            return type("A", (), {"state": type("S", (), {"manifest": type("M", (), {"name": type("N", (), {"value": "Alpha"})()})()})()})()

    coordinator = Coordinator()
    composer = TeamRunViewComposer(coordinator, lifecycle, lambda: lead)
    assert composer.compose(AgentRunView(ToolRegistry((_Tool("read_file"),)))).tools.names == ("read_file", "team")
    coordinator.attached = True
    assert set(composer.compose(AgentRunView(ToolRegistry((_Tool("read_file"),)))).tools.names) == {
        "read_file", "team", "team_member", "team_task", "team_message"
    }
    coordinator.attached = False
    assert "team_member" not in composer.compose(AgentRunView(ToolRegistry([]))).tools.names


class _Permit:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.entries = 0

    @asynccontextmanager
    async def __call__(self):
        self.entries += 1
        if not self.allowed:
            from mewcode.teams.models import TeamPermissionError

            raise TeamPermissionError("current plan is not approved")
        yield


class _TaskService:
    def __init__(self) -> None:
        self.creates = 0

    async def create(self, actor, *, title, description, dependency_ids):
        del actor, title, description, dependency_ids
        self.creates += 1
        return {"task_id": "task-new"}

    def list(self, actor, *, status, assignee):
        del actor, status, assignee
        return ()


class _MailboxService:
    def __init__(self) -> None:
        self.sends = 0

    async def send(self, actor, **arguments):
        del actor, arguments
        self.sends += 1
        return {"message_id": "message-new"}

    def list(self, actor, **arguments):
        del actor, arguments
        return ()


def test_task_and_message_side_effect_actions_use_current_approval_permit(tmp_path) -> None:
    state = state_with_members(tmp_path, 1, FakeClock())
    member = actor(state, "member-1")
    denied = _Permit(False)
    tasks = _TaskService()
    mailbox = _MailboxService()

    task_tool = TeamTaskTool(lambda: tasks, lambda: member, permit=denied)
    task_result = asyncio.run(
        task_tool.execute({"action": "create", "title": "T", "description": "D"})
    )
    message_tool = TeamMessageTool(
        lambda: mailbox,
        lambda: object(),
        lambda: member,
        permit=denied,
    )
    message_result = asyncio.run(
        message_tool.execute(
            {
                "action": "send",
                "recipient": "lead",
                "summary": "status",
                "body": "blocked",
                "protocol": "ordinary",
            }
        )
    )

    assert not task_result.ok and not message_result.ok
    assert tasks.creates == mailbox.sends == 0
    assert denied.entries == 2

    # Read actions never need a side-effect permit, so research stays available.
    assert asyncio.run(task_tool.execute({"action": "list"})).ok
    assert asyncio.run(message_tool.execute({"action": "list"})).ok
    assert denied.entries == 2
