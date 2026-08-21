"""Coordinator cross-layer acceptance scenarios using deterministic member/Git fakes."""

import asyncio
from dataclasses import replace

import pytest

from mewcode.teams.coordinator_models import (
    DecompositionStatus,
    DeliveryKind,
    DeliveryReviewStatus,
    DispatchAction,
)
from mewcode.teams.models import TeamMemberBackend, TeamTaskStatus
from .helpers import actor

from .test_orchestration import (
    _request,
    _service,
    test_in_process_delivery_runs_end_to_end_through_review_and_local_integration as _in_process,
    test_unverified_terminal_backend_is_explicitly_left_pending as _readiness_false,
)
from .test_coordinator_git import (
    test_merge_conflict_is_aborted_back_to_verified_pre_merge_state as _merge_conflict,
    test_recovery_discovers_commit_created_before_journal_confirmation as _commit_recovery,
    test_recovery_treats_unknown_external_head_as_manual_without_reset as _unknown_drift,
)
from .test_coordinator_integration import (
    test_recovery_confirms_observed_commit_without_replaying_merge as _metadata_recovery,
)


def test_in_process_decompose_dispatch_review_and_integrate(tmp_path) -> None:
    _in_process(tmp_path)


def test_readiness_false_refuses_terminal_orchestration(tmp_path) -> None:
    _readiness_false(tmp_path)


@pytest.mark.parametrize(
    "backend",
    (TeamMemberBackend.WINDOWS_TERMINAL, TeamMemberBackend.TMUX),
)
def test_verified_terminal_backend_can_be_dispatched_without_downgrade(tmp_path, backend) -> None:
    service, _states, _repository, _state, scheduler, _mailbox, *_rest = _service(
        tmp_path,
        terminal_verified=True,
        terminal_member=backend,
    )

    async def scenario() -> None:
        run = await service.decompose(_request())
        (run,) = await service.reconcile(run.run_id)
        assert run.decisions[-1].action is DispatchAction.ASSIGN
        assert run.decisions[-1].member_id == "member-1"
        assert scheduler.reserve_calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "backend",
    (TeamMemberBackend.WINDOWS_TERMINAL, TeamMemberBackend.TMUX),
)
def test_readiness_false_refuses_each_terminal_backend(tmp_path, backend) -> None:
    service, _states, _repository, _state, scheduler, _mailbox, *_rest = _service(
        tmp_path,
        terminal_verified=False,
        terminal_member=backend,
    )

    async def scenario() -> None:
        run = await service.decompose(_request())
        (run,) = await service.reconcile(run.run_id)
        assert run.decisions[-1].action is DispatchAction.PENDING
        assert run.decisions[-1].reason_code == "terminal_backends_unverified"
        assert scheduler.reserve_calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "backend",
    (TeamMemberBackend.WINDOWS_TERMINAL, TeamMemberBackend.TMUX),
)
def test_verified_terminal_backend_completes_review_and_integration(tmp_path, backend) -> None:
    service, states, repository, state, _scheduler, _mailbox, tasks, lead, git = _service(
        tmp_path,
        terminal_verified=True,
        terminal_member=backend,
        real_integration=True,
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
        await service.review(
            run.run_id,
            task.task_id,
            DeliveryReviewStatus.ACCEPTED,
            evidence="terminal result verified",
        )
        (run,) = await service.reconcile(run.run_id)
        assert run.status is DecompositionStatus.COMPLETED
        assert repository.list_batches()[0].status.value == "completed"
        assert git.merge_calls == 1

    asyncio.run(scenario())


def test_conflict_rolls_back_and_stops_the_attempt(tmp_path) -> None:
    _merge_conflict(tmp_path)


def test_commit_crash_boundary_is_recognized_without_duplicate_merge(tmp_path) -> None:
    _commit_recovery(tmp_path)


def test_persisted_commit_is_confirmed_without_replay(tmp_path) -> None:
    _metadata_recovery(tmp_path)


def test_unknown_target_drift_is_preserved_for_manual_handling(tmp_path) -> None:
    _unknown_drift(tmp_path)
