from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from mewcode.agent import AgentCapacityPool, AgentRunConfig, AgentRunner, StopReason, ToolScheduler
from mewcode.providers import ProviderTextDelta
from mewcode.teams.models import TeamMemberStatus, TeamMemberOutcomeKind
from mewcode.teams.paths import TeamPaths
from mewcode.teams.runtime import TeamMemberRunBundle, TeamMemberRuntimeFactory, _map_outcome
from mewcode.teams.sessions import MemberSessionStore
from mewcode.tools import ToolRegistry
from mewcode.worktrees import WorktreeNameFactory

from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider
from .helpers import FakeClock, state_with_members, team_name


class _Worktrees:
    def __init__(self, environment) -> None:
        self.environment = environment
        self.suspended = 0

    async def create_or_recover(self, name, *, owner):
        assert name == self.environment.layout.name
        assert owner.owner_id == "member-1"
        return self.environment

    async def enter(self, environment, *, owner):
        return SimpleNamespace(environment=environment, owner=owner, released=False)

    async def suspend(self, lease):
        lease.released = True
        self.suspended += 1


def test_factory_recovers_same_workspace_session_and_releases_resources(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        state = state_with_members(tmp_path, 1, clock)
        name = WorktreeNameFactory().for_team_member(state.manifest.team_id, "member-1")
        root = tmp_path / "member-worktree"
        root.mkdir()
        member = replace(
            state.members["member-1"],
            status=TeamMemberStatus.RUNNING,
            active_run_id="run-1",
            run_generation=1,
            worktree_name=name.value,
            worktree_root=root,
        )
        state = replace(state, members={"member-1": member})
        paths = TeamPaths.for_user(tmp_path, team_name())
        sessions = MemberSessionStore(paths, now=clock.now)
        created = sessions.create(member)
        created.close()
        environment = SimpleNamespace(root=root, layout=SimpleNamespace(name=name))
        worktrees = _Worktrees(environment)

        def build(context):
            assert context.member.member_id == "member-1"
            assert context.history == ()
            assert "member-1" in context.resume_prompt
            provider = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
            runner = AgentRunner(
                provider,
                ToolScheduler(AllowAllPermissionController()),
                AgentRunConfig(max_iterations=2),
            )
            return TeamMemberRunBundle(
                runner.start(
                    context.history,
                    context.resume_prompt,
                    ToolRegistry([]),
                    history_commit_sink=context.session,
                )
            )

        pool = AgentCapacityPool(1)
        capacity = await pool.acquire("team_member", "member-1")
        runtime = await TeamMemberRuntimeFactory(worktrees, sessions, build).create(
            state,
            "member-1",
            capacity,
            reason="new message",
        )
        async for _event in runtime.events():
            pass
        assert runtime.outcome.kind is TeamMemberOutcomeKind.IDLE
        await runtime.close()
        await runtime.close()
        assert worktrees.suspended == 1
        assert pool.active_count == 0

    asyncio.run(scenario())


def test_outcome_mapping_distinguishes_pause_stop_interrupt_and_failure() -> None:
    assert _map_outcome(StopReason.SAFE_PAUSE, "", None, False).kind is TeamMemberOutcomeKind.AWAITING_APPROVAL
    assert _map_outcome(StopReason.CANCELLED, "", None, True).kind is TeamMemberOutcomeKind.STOPPED
    assert _map_outcome(StopReason.CANCELLED, "", None, False).kind is TeamMemberOutcomeKind.INTERRUPTED
    assert _map_outcome(StopReason.ERROR, "", "bad", False).kind is TeamMemberOutcomeKind.FAILED
