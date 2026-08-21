from __future__ import annotations

import asyncio
from dataclasses import replace

from mewcode.teams.coordinator_git import GitTargetSnapshot, MemberGitSnapshot
from mewcode.teams.coordinator_models import (
    COORDINATOR_POLICY_VERSION,
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorSettings,
    DecompositionStatus,
    DeliveryKind,
    DeliveryReviewStatus,
    DispatchAction,
)
from mewcode.teams.coordinator_repository import CoordinatorRepository
from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.models import TeamMemberBackend
from mewcode.teams.orchestration import (
    CoordinatorTaskDraft,
    DecompositionRequest,
    TeamDeliveryCoordinator,
)
from mewcode.teams.repository import TeamRepository
from mewcode.teams.tasks import TeamTaskService
from mewcode.teams.integration import TeamIntegrationService
from mewcode.teams.models import TeamTaskStatus

from .helpers import FakeClock, FakeIds, actor, state_with_members


OID = "1" * 40


class _Reservation:
    owner_id = "member-1"


class _Scheduler:
    def __init__(self) -> None:
        self.active_member_ids = ()
        self.reserved_member_ids = ()
        self.reserve_calls = 0

    async def try_reserve(self, member_id):
        self.reserve_calls += 1
        return _Reservation()

    async def release_reservation(self, reservation):
        del reservation

    async def stop(self, member_id):
        del member_id


class _Mailbox:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush_outbox(self):
        self.flushes += 1


class _Git:
    def __init__(self) -> None:
        self.head = OID
        self.end = "2" * 40
        self.integration_commit = "3" * 40
        self.merge_calls = 0

    async def target_snapshot(self, binding, *, expected_branch=None, expected_oid=None, require_clean=True):
        del binding, require_clean
        if expected_oid is not None:
            assert expected_oid == self.head
        return GitTargetSnapshot(expected_branch or "refs/heads/main", self.head, True, False)

    async def member_head(self, binding, team_id, member):
        del binding, team_id
        return OID, f"refs/heads/mewcode/worktree/{member.worktree_name}", member.worktree_root

    async def inspect_member(self, binding, team_id, member, *, start_oid):
        del binding, team_id
        return MemberGitSnapshot(
            member.member_id,
            member.worktree_root,
            f"refs/heads/mewcode/worktree/{member.worktree_name}",
            start_oid,
            self.end,
            (self.end,),
            ("result.txt",),
        )

    async def begin_merge(self, binding, step, *, target_branch):
        del binding, step, target_branch
        self.merge_calls += 1
        return self.head

    async def create_integration_commit(self, binding, **arguments):
        del binding, arguments
        self.head = self.integration_commit
        return self.head

    async def verify_integration_commit(self, binding, step, commit_oid, *, team_id=None):
        del binding, step, team_id
        assert commit_oid == self.head

    async def rollback(self, binding, *, pre_oid):
        del binding
        self.head = pre_oid


class _Integration:
    async def recover(self, binding):
        del binding
        return ()


def _service(tmp_path, *, terminal_verified=True, terminal_member=False, real_integration=False):
    clock = FakeClock()
    state = state_with_members(tmp_path, count=1, clock=clock)
    if terminal_member:
        backend = terminal_member if isinstance(terminal_member, TeamMemberBackend) else TeamMemberBackend.TMUX
        member = replace(state.members["member-1"], backend=backend)
        state = replace(state, members={"member-1": member})
    states = TeamRepository(tmp_path / "teams", now=clock.now)
    states.create(state)
    lease = asyncio.run(
        TeamLeaseService(states, now=clock.now, new_id=FakeIds()).acquire(
            state.manifest.name, root_session_id="root", process_id="process",
        )
    )
    lead = actor(state, fence=lease.fence)
    coordinator = CoordinatorRepository(states, state.manifest.name)
    settings = CoordinatorSettings(
        COORDINATOR_SCHEMA_VERSION, True, True, True, COORDINATOR_POLICY_VERSION,
        terminal_verified, clock.now(),
    )
    coordinator.initialize(settings)
    scheduler = _Scheduler()
    mailbox = _Mailbox()
    git = _Git()
    integration = TeamIntegrationService(coordinator, git, now=clock.now) if real_integration else _Integration()
    task_service = TeamTaskService(states, state.manifest.name, now=clock.now, new_id=FakeIds())
    service = TeamDeliveryCoordinator(
        settings,
        states,
        coordinator,
        state.manifest.name,
        lead,
        task_service,
        mailbox,
        scheduler,
        git,
        integration,
        now=clock.now,
        new_id=FakeIds(),
    )
    return service, states, coordinator, state, scheduler, mailbox, task_service, lead, git


def _request() -> DecompositionRequest:
    return DecompositionRequest(
        "implement a feature",
        "refs/heads/main",
        (
            CoordinatorTaskDraft(
                "task", "Implement", "Implementation details", (), "member-1", None,
                ("write_file",), ("tests pass",), DeliveryKind.NO_GIT,
            ),
        ),
    )


def test_decomposition_publication_and_dispatch_are_auditable(tmp_path) -> None:
    service, states, _repository, state, scheduler, mailbox, _tasks, _lead, _git = _service(tmp_path)

    async def scenario() -> None:
        run = await service.decompose(_request())
        assert run.status is DecompositionStatus.ACTIVE
        assert tuple(states.load(state.manifest.name).tasks) == (run.tasks[0].task_id,)
        (updated,) = await service.reconcile(run.run_id)
        assert updated.decisions[-1].action is DispatchAction.ASSIGN
        assert scheduler.reserve_calls == 1
        assert mailbox.flushes == 1
        task = states.load(state.manifest.name).tasks[run.tasks[0].task_id]
        assert task.assignee_id == "member-1"

    asyncio.run(scenario())


def test_unverified_terminal_backend_is_explicitly_left_pending(tmp_path) -> None:
    service, states, _repository, state, scheduler, _mailbox, _tasks, _lead, _git = _service(
        tmp_path, terminal_verified=False, terminal_member=True,
    )

    async def scenario() -> None:
        run = await service.decompose(_request())
        (updated,) = await service.reconcile(run.run_id)
        assert updated.decisions[-1].action is DispatchAction.PENDING
        assert updated.decisions[-1].reason_code == "terminal_backends_unverified"
        assert scheduler.reserve_calls == 0
        task = states.load(state.manifest.name).tasks[run.tasks[0].task_id]
        assert task.assignee_id is None

    asyncio.run(scenario())


def test_in_process_delivery_runs_end_to_end_through_review_and_local_integration(tmp_path) -> None:
    service, states, repository, state, _scheduler, _mailbox, tasks, lead, git = _service(
        tmp_path, real_integration=True,
    )
    base_request = _request()
    request = replace(
        base_request,
        tasks=(replace(base_request.tasks[0], delivery_kind=DeliveryKind.GIT),),
        auto_integrate=True,
    )

    async def scenario() -> None:
        run = await service.decompose(request)
        (run,) = await service.reconcile(run.run_id)
        task = states.load(state.manifest.name).tasks[run.tasks[0].task_id]
        member_actor = actor(states.load(state.manifest.name), "member-1", lead.lease_fence)
        started = await tasks.transition(
            member_actor, task.task_id, TeamTaskStatus.IN_PROGRESS,
            expected_revision=task.revision,
        )
        await tasks.transition(
            member_actor, task.task_id, TeamTaskStatus.COMPLETED,
            expected_revision=started.task.revision,
            result="done",
        )
        (run,) = await service.reconcile(run.run_id)
        assert run.reviews[0].status.value == "pending"
        run = await service.review(
            run.run_id, task.task_id, DeliveryReviewStatus.ACCEPTED,
            evidence="acceptance checks passed",
        )
        (run,) = await service.reconcile(run.run_id)
        assert run.status is DecompositionStatus.COMPLETED
        batches = repository.list_batches()
        assert len(batches) == 1 and batches[0].status.value == "completed"
        assert git.merge_calls == 1 and git.head == git.integration_commit

    asyncio.run(scenario())


def test_accepted_git_review_is_invalidated_when_member_head_changes(tmp_path) -> None:
    service, states, _repository, state, _scheduler, _mailbox, tasks, lead, git = _service(
        tmp_path, real_integration=True,
    )
    base_request = _request()
    request = replace(
        base_request,
        tasks=(replace(base_request.tasks[0], delivery_kind=DeliveryKind.GIT),),
    )

    async def scenario() -> None:
        run = await service.decompose(request)
        (run,) = await service.reconcile(run.run_id)
        task = states.load(state.manifest.name).tasks[run.tasks[0].task_id]
        member_actor = actor(states.load(state.manifest.name), "member-1", lead.lease_fence)
        started = await tasks.transition(
            member_actor, task.task_id, TeamTaskStatus.IN_PROGRESS,
            expected_revision=task.revision,
        )
        await tasks.transition(
            member_actor, task.task_id, TeamTaskStatus.COMPLETED,
            expected_revision=started.task.revision,
            result="done",
        )
        (run,) = await service.reconcile(run.run_id)
        run = await service.review(
            run.run_id, task.task_id, DeliveryReviewStatus.ACCEPTED,
            evidence="checked",
        )
        git.end = "4" * 40
        (run,) = await service.reconcile(run.run_id)
        assert run.status is DecompositionStatus.ACTIVE
        assert run.reviews[0].status is DeliveryReviewStatus.PENDING
        assert run.reviews[0].worktree_end_oid == git.end

    asyncio.run(scenario())
