from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mewcode.teams.domain import (
    assign_task,
    claim_task,
    create_task,
    enqueue_member,
    task_view,
    transition_member,
    transition_task,
    update_task,
    validate_team_state,
)
from mewcode.teams.coordinator_models import CoordinatorTaskSpec, DeliveryKind
from mewcode.teams.models import (
    MailboxRegistration,
    MemberWakeReason,
    TeamActor,
    TeamActorKind,
    TeamMemberBackend,
    TeamMemberRecord,
    TeamMemberStatus,
    TeamTaskStatus,
    TeamValidationError,
)

from .helpers import FakeClock, empty_state, role, team_name
from .helpers import FakeIds, actor as shared_actor, state_with_members
from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.repository import TeamRepository
from mewcode.teams.tasks import TeamTaskService
import asyncio


def _state_with_members(tmp_path: Path):
    clock = FakeClock()
    state = empty_state(tmp_path, clock)
    members = {}
    registry = {}
    for index in (1, 2):
        member_id = f"member-{index}"
        name = team_name(f"member-{index}")
        member = TeamMemberRecord(
            member_id=member_id,
            name=name,
            role=role(clock),
            backend=TeamMemberBackend.IN_PROCESS,
            requires_approval=False,
            status=TeamMemberStatus.IDLE,
            worktree_name=f"team/a/member-{index}",
            worktree_root=tmp_path / member_id,
            worktree_owner_id=member_id,
            mailbox_name=f"{member_id}.jsonl",
            session_name=f"{member_id}.jsonl",
            current_task_id=None,
            active_run_id=None,
            run_generation=0,
            last_error=None,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        members[member_id] = member
        registry[name.canonical_key] = MailboxRegistration(member_id, name, member.mailbox_name, False)
    return replace(state, members=members, registry=registry), clock


def _actor(state, member_id: str | None = None) -> TeamActor:
    if member_id is None:
        return TeamActor("lead", team_name("lead"), TeamActorKind.LEAD, state.manifest.team_id, ("lease-1", 1))
    return TeamActor(member_id, state.members[member_id].name, TeamActorKind.MEMBER, state.manifest.team_id, ("lease-1", 1))


def test_member_state_machine_rejects_illegal_transition(tmp_path) -> None:
    state, clock = _state_with_members(tmp_path)
    queued = transition_member(state, "member-1", TeamMemberStatus.QUEUED, now=clock.now())
    running = transition_member(queued, "member-1", TeamMemberStatus.RUNNING, now=clock.now(), active_run_id="run-1")
    assert running.members["member-1"].run_generation == 1
    with pytest.raises(TeamValidationError):
        transition_member(state, "member-1", TeamMemberStatus.RUNNING, now=clock.now(), active_run_id="run-1")


def test_dependency_validation_blocking_and_cycle(tmp_path) -> None:
    state, clock = _state_with_members(tmp_path)
    state, first = create_task(state, _actor(state), task_id="task-1", title="one", description="", dependency_ids=(), now=clock.now())
    state, second = create_task(state, _actor(state), task_id="task-2", title="two", description="", dependency_ids=("task-1",), now=clock.now())
    assert second.blocked is True
    with pytest.raises(TeamValidationError):
        update_task(state, _actor(state), "task-1", expected_revision=0, dependency_ids=("task-2",), now=clock.now())
    state, _ = transition_task(state, _actor(state), "task-1", TeamTaskStatus.IN_PROGRESS, expected_revision=0, result="", now=clock.now())
    state, _ = transition_task(state, _actor(state), "task-1", TeamTaskStatus.COMPLETED, expected_revision=1, result="done", now=clock.now())
    assert task_view(state, state.tasks["task-2"]).claimable is True


def test_assign_claim_and_queue_are_single_owner(tmp_path) -> None:
    state, clock = _state_with_members(tmp_path)
    state, _ = create_task(state, _actor(state), task_id="task-1", title="one", description="", dependency_ids=(), now=clock.now())
    claimed, view = claim_task(state, _actor(state, "member-1"), "task-1", expected_revision=0, now=clock.now())
    assert view.task.assignee_id == "member-1"
    with pytest.raises(TeamValidationError):
        claim_task(claimed, _actor(claimed, "member-2"), "task-1", expected_revision=0, now=clock.now())
    queued, first = enqueue_member(claimed, "member-1", queue_id="queue-1", reason=MemberWakeReason.MESSAGE, message_ids=("m1",), now=clock.now())
    queued, merged = enqueue_member(queued, "member-1", queue_id="queue-2", reason=MemberWakeReason.MESSAGE, message_ids=("m2",), now=clock.now())
    assert first is not None and merged is not None
    assert len(queued.queue) == 1
    assert merged.message_ids == ("m1", "m2")
    validate_team_state(queued)


def test_task_service_commits_assignment_and_terminal_outbox(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, clock=clock))
    leases = TeamLeaseService(repository, now=clock.now, new_id=ids)

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        lead = shared_actor(state, fence=lease.fence)
        service = TeamTaskService(repository, state.manifest.name, now=clock.now, new_id=ids)
        created = await service.create(lead, title="implement", description="details")
        assigned = await service.assign(lead, created.task.task_id, "member-1", expected_revision=0)
        assert assigned.task.assignee_id == "member-1"
        committed = repository.load(state.manifest.name)
        assert committed.outbox[-1].message.protocol.value == "task_assignment"
        member = shared_actor(committed, "member-1", lease.fence)
        started = await service.transition(member, created.task.task_id, TeamTaskStatus.IN_PROGRESS, expected_revision=1)
        await service.transition(member, created.task.task_id, TeamTaskStatus.COMPLETED, expected_revision=2, result="done")
        assert repository.load(state.manifest.name).outbox[-1].message.protocol.value == "task_status"

    asyncio.run(scenario())


def test_task_service_publishes_coordinator_batch_atomically_and_idempotently(tmp_path) -> None:
    clock = FakeClock()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, clock=clock))
    leases = TeamLeaseService(repository, now=clock.now, new_id=FakeIds())
    specs = (
        CoordinatorTaskSpec(
            "second", "task-2", 1, "second", "depends on first",
            ("first",), ("task-1",), "member-2", None, (), ("tests pass",),
            DeliveryKind.GIT,
        ),
        CoordinatorTaskSpec(
            "first", "task-1", 0, "first", "foundation",
            (), (), "member-1", None, (), ("tests pass",), DeliveryKind.GIT,
        ),
    )

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        lead = shared_actor(state, fence=lease.fence)
        service = TeamTaskService(repository, state.manifest.name, now=clock.now)
        created = await service.create_batch(lead, specs)
        repeated = await service.create_batch(lead, specs)
        assert [item.task.task_id for item in created] == ["task-1", "task-2"]
        assert [item.task.task_id for item in repeated] == ["task-1", "task-2"]
        assert repository.load(state.manifest.name).revision == 1

    asyncio.run(scenario())
