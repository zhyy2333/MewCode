from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from mewcode.agent import AgentRunConfig, AgentRunner, StopReason, ToolScheduler
from mewcode.providers import ProviderTextDelta
from mewcode.teams.member_worker import (
    MEMBER_RUN_SCHEMA_VERSION, ManagedMemberWorker, MemberRunDescriptor,
    MemberRunDescriptorStore, run_member_worker_file,
)
from mewcode.teams.models import TeamMemberStatus, TeamValidationError
from mewcode.teams.paths import TeamPaths
from mewcode.teams.runtime import TeamMemberRunBundle, TeamMemberRuntimeFactory
from mewcode.teams.sessions import MemberSessionStore
from mewcode.tools import ToolRegistry

from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider
from .helpers import FakeClock, state_with_members, team_name
from .test_runtime import _Worktrees
from types import SimpleNamespace
from mewcode.worktrees import WorktreeNameFactory


def test_worker_validates_running_identity_and_writes_atomic_result(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        state = state_with_members(tmp_path, 1, clock)
        name = WorktreeNameFactory().for_team_member(state.manifest.team_id, "member-1")
        root = tmp_path / "member-worktree"
        root.mkdir()
        member = replace(state.members["member-1"], status=TeamMemberStatus.RUNNING, active_run_id="run-1", run_generation=1, worktree_name=name.value, worktree_root=root)
        state = replace(state, members={"member-1": member})
        paths = TeamPaths.for_user(tmp_path, team_name())
        sessions = MemberSessionStore(paths, now=clock.now)
        created = sessions.create(member)
        created.close()
        worktrees = _Worktrees(SimpleNamespace(root=root, layout=SimpleNamespace(name=name)))
        def build(context):
            return TeamMemberRunBundle(AgentRunner(ScriptedAsyncProvider([[ProviderTextDelta("done")]]), ToolScheduler(AllowAllPermissionController()), AgentRunConfig(max_iterations=2)).start(context.history, context.resume_prompt, ToolRegistry([]), history_commit_sink=context.session))
        store = MemberRunDescriptorStore(paths)
        descriptor = MemberRunDescriptor(MEMBER_RUN_SCHEMA_VERSION, state.manifest.team_id, "member-1", "run-1", 1, "message", clock.now())
        store.write_descriptor(descriptor)
        result = await ManagedMemberWorker(TeamMemberRuntimeFactory(worktrees, sessions, build), store, state, now=clock.now).run(store.read_descriptor("member-1", "run-1"))
        assert result.outcome.kind.value == "idle"
        assert store.read_result("member-1", "run-1") == result
        assert worktrees.suspended == 1
    asyncio.run(scenario())


def test_worker_rejects_stale_descriptor(tmp_path) -> None:
    state = state_with_members(tmp_path, 1)
    descriptor = MemberRunDescriptor(MEMBER_RUN_SCHEMA_VERSION, state.manifest.team_id, "member-1", "run-1", 1, "message", FakeClock().now())
    worker = ManagedMemberWorker(None, MemberRunDescriptorStore(TeamPaths.for_user(tmp_path, team_name())), state)  # type: ignore[arg-type]
    with pytest.raises(TeamValidationError, match="stale"):
        worker._validate(descriptor)


def test_hidden_worker_entry_uses_supplied_shared_runtime_factory(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        state = state_with_members(tmp_path, 1, clock)
        name = WorktreeNameFactory().for_team_member(state.manifest.team_id, "member-1")
        root = tmp_path / "worker-worktree"
        root.mkdir()
        member = replace(state.members["member-1"], status=TeamMemberStatus.RUNNING, active_run_id="run-1", run_generation=1, worktree_name=name.value, worktree_root=root)
        state = replace(state, members={"member-1": member})
        paths = TeamPaths.for_user(tmp_path, team_name())
        sessions = MemberSessionStore(paths, now=clock.now)
        created = sessions.create(member); created.close()
        worktrees = _Worktrees(SimpleNamespace(root=root, layout=SimpleNamespace(name=name)))
        def build(context):
            return TeamMemberRunBundle(AgentRunner(ScriptedAsyncProvider([[ProviderTextDelta("done")]]), ToolScheduler(AllowAllPermissionController()), AgentRunConfig(max_iterations=2)).start(context.history, context.resume_prompt, ToolRegistry([]), history_commit_sink=context.session))
        descriptor = MemberRunDescriptor(MEMBER_RUN_SCHEMA_VERSION, state.manifest.team_id, "member-1", "run-1", 1, "mail", clock.now())
        run_file = MemberRunDescriptorStore(paths).write_descriptor(descriptor)
        factory = TeamMemberRuntimeFactory(worktrees, sessions, build)
        assert await run_member_worker_file(run_file, runtime_factory=factory, state_loader=lambda team_id: state) == 0
        assert MemberRunDescriptorStore(paths).read_result("member-1", "run-1").outcome.kind.value == "idle"
    asyncio.run(scenario())


def test_worker_records_are_single_publish_and_preserve_existing_file(tmp_path) -> None:
    clock = FakeClock()
    paths = TeamPaths.for_user(tmp_path, team_name())
    store = MemberRunDescriptorStore(paths)
    descriptor = MemberRunDescriptor(
        MEMBER_RUN_SCHEMA_VERSION, "team-1", "member-1", "run-1", 1, "mail", clock.now()
    )
    path = store.write_descriptor(descriptor)
    original = path.read_bytes()
    with pytest.raises(Exception, match="already exists"):
        store.write_descriptor(descriptor)
    assert path.read_bytes() == original
