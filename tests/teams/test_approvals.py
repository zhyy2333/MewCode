from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from mewcode.teams.approvals import TeamApprovalService
from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.models import PlanDecision, TeamMemberStatus, TeamPermissionError
from mewcode.teams.repository import TeamRepository
from mewcode.teams.tasks import TeamTaskService

from .helpers import FakeClock, FakeIds, actor, state_with_members


def test_approval_request_decision_permit_and_invalidation(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    state = state_with_members(tmp_path, clock=clock)
    members = dict(state.members)
    members["member-1"] = replace(members["member-1"], requires_approval=True)
    state = replace(state, members=members)
    repository = TeamRepository(tmp_path, now=clock.now)
    repository.create(state)
    leases = TeamLeaseService(repository, now=clock.now, new_id=ids)

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        lead = actor(state, fence=lease.fence)
        tasks = TeamTaskService(repository, state.manifest.name, now=clock.now, new_id=ids)
        created = await tasks.create(lead, title="change", description="details")
        await tasks.assign(lead, created.task.task_id, "member-1", expected_revision=0)
        current = repository.load(state.manifest.name)
        member = actor(current, "member-1", lease.fence)
        approvals = TeamApprovalService(repository, state.manifest.name, now=clock.now, new_id=ids)
        with pytest.raises(TeamPermissionError):
            async with approvals.side_effect_permit(member, created.task.task_id):
                pass
        request = await approvals.request(
            member, task_id=created.task.task_id, plan_version=1,
            plan_text="1. edit\n2. test", summary="implementation plan",
        )
        assert repository.load(state.manifest.name).members["member-1"].status is TeamMemberStatus.AWAITING_APPROVAL
        decided = await approvals.decide(lead, request_id=request.request_id, decision=PlanDecision.APPROVE, feedback=None)
        assert decided.decision is PlanDecision.APPROVE
        async with approvals.side_effect_permit(member, created.task.task_id) as permit:
            assert permit.request_id == request.request_id
        await approvals.invalidate_for_task(created.task.task_id, reason="dependency changed", lease_fence=lease.fence)
        with pytest.raises(TeamPermissionError):
            async with approvals.side_effect_permit(member, created.task.task_id):
                pass

    asyncio.run(scenario())
