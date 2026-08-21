from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from mewcode.teams import domain
from mewcode.teams.coordinator_git import CoordinatorGitBackend
from mewcode.teams.coordinator_models import (
    COORDINATOR_POLICY_VERSION,
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorSettings,
    CoordinatorTaskSpec,
    DecompositionRun,
    DecompositionStatus,
    DeliveryKind,
    DeliveryReview,
    DeliveryReviewStatus,
    IntegrationBatchStatus,
    IntegrationBatch,
    IntegrationStep,
    IntegrationStepStatus,
    CoordinatorJournal,
    CoordinatorJournalEntry,
    JournalBoundary,
    RecoveryDecisionKind,
)
from mewcode.teams.coordinator_git import GitRecoveryDecision
from mewcode.teams.coordinator_repository import CoordinatorRepository
from mewcode.teams.integration import TeamIntegrationService
from mewcode.teams.models import TeamTaskStatus
from mewcode.teams.repository import TeamRepository

from .helpers import FakeClock, actor, state_with_members, empty_state
from .test_coordinator_git import _repository


def test_plan_and_execute_follow_stable_dependency_order(tmp_path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    binding, base, end = _repository(repository_root)
    clock = FakeClock(datetime.now(timezone.utc))
    state = state_with_members(repository_root, count=1, clock=clock)
    state = replace(state, manifest=replace(state.manifest, repository=binding))
    lead = actor(state)
    member = actor(state, "member-1")
    state, _ = domain.create_task(
        state, lead, task_id="task-1", title="delivery", description="details",
        dependency_ids=(), now=clock.now(),
    )
    state, _ = domain.assign_task(
        state, lead, "task-1", "member-1", expected_revision=0, now=clock.now(),
    )
    state, _ = domain.transition_task(
        state, member, "task-1", TeamTaskStatus.IN_PROGRESS, expected_revision=1,
        result="", now=clock.now(),
    )
    state, _ = domain.transition_task(
        state, member, "task-1", TeamTaskStatus.COMPLETED, expected_revision=2,
        result="done", now=clock.now(),
    )
    teams = TeamRepository(tmp_path / "teams", now=clock.now)
    teams.create(state)
    coordinator = CoordinatorRepository(teams, state.manifest.name)
    coordinator.initialize(
        CoordinatorSettings(
            COORDINATOR_SCHEMA_VERSION, True, True, True, COORDINATOR_POLICY_VERSION,
            True, clock.now(),
        )
    )
    task = state.tasks["task-1"]
    run = DecompositionRun(
        COORDINATOR_SCHEMA_VERSION, 0, "run-1", state.manifest.team_id, "deliver result",
        "refs/heads/main", base, True,
        (
            CoordinatorTaskSpec(
                "local-1", "task-1", 0, "delivery", "details", (), (), "member-1",
                None, (), ("result is committed",), DeliveryKind.GIT,
            ),
        ),
        (), DecompositionStatus.READY_TO_INTEGRATE, None, clock.now(), clock.now(),
        (
            DeliveryReview(
                "task-1", "member-1", task.revision, base, end, (end,),
                DeliveryReviewStatus.ACCEPTED, "verified by tests", clock.now(),
            ),
        ),
    )
    coordinator.create_decomposition(run)
    service = TeamIntegrationService(coordinator, CoordinatorGitBackend(), now=clock.now)
    batch = service.plan(run, state)

    async def scenario() -> None:
        completed = await service.execute(batch.batch_id, binding)
        assert completed.status is IntegrationBatchStatus.COMPLETED
        assert completed.next_step == 1

    asyncio.run(scenario())


def test_stable_topology_uses_ordinal_as_tie_breaker(tmp_path) -> None:
    del tmp_path
    now = datetime.now(timezone.utc)
    oid = "1" * 40
    tasks = (
        CoordinatorTaskSpec("a", "task-a", 0, "a", "a", (), (), "m", None, (), ("ok",), DeliveryKind.GIT),
        CoordinatorTaskSpec("b", "task-b", 1, "b", "b", (), (), "m", None, (), ("ok",), DeliveryKind.GIT),
        CoordinatorTaskSpec("c", "task-c", 2, "c", "c", ("a", "b"), ("task-a", "task-b"), "m", None, (), ("ok",), DeliveryKind.GIT),
    )
    run = DecompositionRun(
        COORDINATOR_SCHEMA_VERSION, 0, "run", "team", "goal", "refs/heads/main", oid,
        False, tasks, (), DecompositionStatus.ACTIVE, None, now, now,
    )
    assert TeamIntegrationService.stable_topology(run) == ("task-a", "task-b", "task-c")


def test_recovery_confirms_observed_commit_without_replaying_merge(tmp_path) -> None:
    clock = FakeClock(datetime.now(timezone.utc))
    teams = TeamRepository(tmp_path / "teams", now=clock.now)
    state = teams.create(empty_state(tmp_path, clock))
    coordinator = CoordinatorRepository(teams, state.manifest.name)
    coordinator.initialize(
        CoordinatorSettings(
            COORDINATOR_SCHEMA_VERSION, True, True, True, COORDINATOR_POLICY_VERSION,
            True, clock.now(),
        )
    )
    pre, end, commit = "1" * 40, "2" * 40, "3" * 40
    step = IntegrationStep(
        COORDINATOR_SCHEMA_VERSION, 0, "step-1", "batch-1", 0, "task-1", "member-1",
        tmp_path, "refs/heads/member", pre, end, (end,), pre, pre, commit, None,
        IntegrationStepStatus.COMMIT_OBSERVED, None, clock.now(), clock.now(),
    )
    batch = IntegrationBatch(
        COORDINATOR_SCHEMA_VERSION, 0, "batch-1", state.manifest.team_id, "run-1",
        "refs/heads/main", pre, ("task-1",), ("task-1",), ("step-1",), 0,
        IntegrationBatchStatus.RUNNING, None, clock.now(), clock.now(),
    )
    coordinator.create_journal(
        CoordinatorJournal(
            COORDINATOR_SCHEMA_VERSION, 0, "step-1", state.manifest.team_id,
            "integration_step", "step-1",
            (
                CoordinatorJournalEntry(0, JournalBoundary.PREPARED, "task-1", None, None, None, clock.now()),
                CoordinatorJournalEntry(1, JournalBoundary.MERGE_STARTED, "task-1", pre, None, None, clock.now()),
                CoordinatorJournalEntry(2, JournalBoundary.COMMIT_CREATED, "task-1", pre, commit, None, clock.now()),
            ),
        )
    )
    coordinator.create_batch(batch, (step,))

    class RecoveryGit:
        verifies = 0
        merges = 0

        async def recovery_decision(self, binding, current):
            del binding, current
            return GitRecoveryDecision(RecoveryDecisionKind.CONFIRM, "commit_observed", commit)

        async def verify_integration_commit(self, binding, current, oid, *, team_id=None):
            del binding, current, team_id
            assert oid == commit
            self.verifies += 1

    git = RecoveryGit()
    service = TeamIntegrationService(coordinator, git, now=clock.now)  # type: ignore[arg-type]

    async def scenario() -> None:
        (recovered,) = await service.recover(state.manifest.repository)
        assert recovered.status is IntegrationBatchStatus.COMPLETED
        assert coordinator.load_step("step-1").status is IntegrationStepStatus.VERIFIED
        assert git.verifies == 1 and git.merges == 0

    asyncio.run(scenario())
