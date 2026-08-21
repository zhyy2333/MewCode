from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import uuid

from .coordinator_git import CoordinatorGitBackend, CoordinatorGitError
from .coordinator_models import (
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorJournal,
    CoordinatorJournalEntry,
    DecompositionRun,
    DeliveryKind,
    DeliveryReviewStatus,
    IntegrationBatch,
    IntegrationBatchStatus,
    IntegrationStep,
    IntegrationStepStatus,
    JournalBoundary,
    RecoveryDecisionKind,
    transition_batch,
    transition_step,
)
from .coordinator_repository import CoordinatorRepository
from .models import RepositoryBinding, TeamState, TeamTaskStatus, TeamValidationError


class TeamIntegrationService:
    def __init__(
        self,
        repository: CoordinatorRepository,
        git: CoordinatorGitBackend,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._repository = repository
        self._git = git
        self._now = now
        self._new_id = new_id

    def plan(self, run: DecompositionRun, state: TeamState) -> IntegrationBatch:
        if run.team_id != state.manifest.team_id:
            raise TeamValidationError("Integration run belongs to another team.")
        existing = tuple(
            item for item in self._repository.list_batches()
            if item.decomposition_run_id == run.run_id
        )
        if existing:
            if len(existing) != 1:
                raise TeamValidationError("Decomposition has multiple integration batches.")
            return existing[0]
        reviews = {item.task_id: item for item in run.reviews}
        specs = {item.task_id: item for item in run.tasks}
        for task_id, spec in specs.items():
            task = state.tasks.get(task_id)
            review = reviews.get(task_id)
            if task is None or task.status is not TeamTaskStatus.COMPLETED:
                raise TeamValidationError("Every decomposition task must complete before integration.")
            if review is None or review.status is not DeliveryReviewStatus.ACCEPTED:
                raise TeamValidationError("Every decomposition task requires an accepted delivery review.")
            if task.assignee_id != review.member_id or task.revision != review.task_revision:
                raise TeamValidationError("A delivery review no longer matches its task.")
            if spec.delivery_kind is DeliveryKind.GIT and not review.commit_oids:
                raise TeamValidationError("A Git delivery review has no frozen commit range.")
            if spec.delivery_kind is DeliveryKind.NO_GIT and review.commit_oids:
                raise TeamValidationError("A no-Git delivery unexpectedly contains commits.")

        git_ids = {item.task_id for item in run.tasks if item.delivery_kind is DeliveryKind.GIT}
        topology = self.stable_topology(run, git_ids)
        if not topology:
            raise TeamValidationError("The decomposition has no Git delivery to integrate.")
        batch_id = self._stable_id("batch", run.run_id)
        created_at = self._now()
        steps: list[IntegrationStep] = []
        for ordinal, task_id in enumerate(topology):
            review = reviews[task_id]
            member = state.members[review.member_id]
            step_id = self._stable_id("step", run.run_id, task_id)
            planned_step = IntegrationStep(
                    COORDINATOR_SCHEMA_VERSION,
                    0,
                    step_id,
                    batch_id,
                    ordinal,
                    task_id,
                    review.member_id,
                    member.worktree_root,
                    f"refs/heads/mewcode/worktree/{member.worktree_name}",
                    review.worktree_start_oid or "",
                    review.worktree_end_oid or "",
                    review.commit_oids,
                    run.target_baseline_oid,
                    None,
                    None,
                    None,
                    IntegrationStepStatus.PREPARED,
                    None,
                    created_at,
                    created_at,
                )
            step_path = self._repository.paths.coordinator_step_file(step_id)
            if step_path.exists():
                existing_step = self._repository.load_step(step_id)
                if replace(existing_step, created_at=created_at, updated_at=created_at) != planned_step:
                    raise TeamValidationError("Recovered integration step conflicts with the plan.")
                planned_step = existing_step
            steps.append(planned_step)
        batch = IntegrationBatch(
            COORDINATOR_SCHEMA_VERSION,
            0,
            batch_id,
            run.team_id,
            run.run_id,
            run.target_branch,
            run.target_baseline_oid,
            topology,
            topology,
            tuple(item.step_id for item in steps),
            0,
            IntegrationBatchStatus.PREPARED,
            None,
            created_at,
            created_at,
        )
        for step in steps:
            journal = CoordinatorJournal(
                    COORDINATOR_SCHEMA_VERSION,
                    0,
                    step.step_id,
                    run.team_id,
                    "integration_step",
                    step.step_id,
                    (self._entry(JournalBoundary.PREPARED, task_id=step.task_id),),
                )
            if self._repository.paths.coordinator_journal_file(step.step_id).exists():
                existing_journal = self._repository.load_journal(step.step_id)
                if (
                    existing_journal.team_id != journal.team_id
                    or existing_journal.operation_kind != journal.operation_kind
                    or existing_journal.operation_id != journal.operation_id
                    or not existing_journal.entries
                    or existing_journal.entries[0].boundary is not JournalBoundary.PREPARED
                    or existing_journal.entries[0].task_id != step.task_id
                ):
                    raise TeamValidationError("Integration journal conflicts with the recovered plan.")
            else:
                self._repository.create_journal(journal)
        self._repository.create_batch(batch, tuple(steps))
        return batch

    @staticmethod
    def _stable_id(kind: str, *values: str) -> str:
        digest = hashlib.sha256("\x00".join(values).encode("utf-8")).hexdigest()
        return f"{kind}-{digest}"

    async def execute(self, batch_id: str, binding: RepositoryBinding) -> IntegrationBatch:
        batch = self._repository.load_batch(batch_id)
        with self._repository.branch_lock(binding.repository_id, batch.target_branch):
            if batch.status is IntegrationBatchStatus.PREPARED:
                batch = self._save_batch(
                    batch,
                    transition_batch(batch, IntegrationBatchStatus.RUNNING, now=self._now()),
                )
            if batch.status is not IntegrationBatchStatus.RUNNING:
                return batch
            for ordinal in range(batch.next_step, len(batch.step_ids)):
                step = self._repository.load_step(batch.step_ids[ordinal])
                if step.status is IntegrationStepStatus.VERIFIED:
                    current = self._repository.load_batch(batch.batch_id)
                    batch = self._advance_batch(current, step.ordinal + 1)
                    continue
                try:
                    batch, step = await self._execute_step(batch, step, binding)
                except (CoordinatorGitError, OSError) as exc:
                    code = exc.code if isinstance(exc, CoordinatorGitError) else "git_io_failed"
                    await self._rollback_failed_step(step, binding, code)
                    current = self._repository.load_batch(batch.batch_id)
                    failed = transition_batch(
                        current,
                        IntegrationBatchStatus.FAILED,
                        now=self._now(),
                        diagnostic=code,
                    )
                    return self._save_batch(current, failed)
            current = self._repository.load_batch(batch.batch_id)
            completed = transition_batch(
                current,
                IntegrationBatchStatus.COMPLETED,
                now=self._now(),
                next_step=len(current.step_ids),
            )
            return self._save_batch(current, completed)

    async def recover(self, binding: RepositoryBinding) -> tuple[IntegrationBatch, ...]:
        results: list[IntegrationBatch] = []
        for batch in self._repository.list_batches(active_only=True):
            with self._repository.branch_lock(binding.repository_id, batch.target_branch):
                if batch.next_step >= len(batch.step_ids):
                    results.append(batch)
                    continue
                step = self._repository.load_step(batch.step_ids[batch.next_step])
                if step.status is IntegrationStepStatus.VERIFIED:
                    current = self._repository.load_batch(batch.batch_id)
                    self._advance_batch(current, step.ordinal + 1)
                if step.status in {IntegrationStepStatus.MERGING, IntegrationStepStatus.COMMIT_OBSERVED}:
                    if step.integration_commit_oid is None:
                        journal = self._repository.load_journal(step.step_id)
                        observed_oid = next(
                            (
                                item.result_oid for item in reversed(journal.entries)
                                if item.boundary is JournalBoundary.COMMIT_CREATED and item.result_oid is not None
                            ),
                            None,
                        )
                        if observed_oid is not None:
                            observed = transition_step(
                                step,
                                IntegrationStepStatus.COMMIT_OBSERVED,
                                now=self._now(),
                                integration_commit_oid=observed_oid,
                            )
                            step = self._save_step(step, observed)
                    decision = await self._git.recovery_decision(binding, step)
                    if decision.kind is RecoveryDecisionKind.CONFIRM:
                        try:
                            if step.integration_commit_oid is None:
                                observed = transition_step(
                                    step,
                                    IntegrationStepStatus.COMMIT_OBSERVED,
                                    now=self._now(),
                                    integration_commit_oid=decision.observed_head_oid,
                                )
                                step = self._save_step(step, observed)
                            await self._git.verify_integration_commit(
                                binding, step, step.integration_commit_oid or decision.observed_head_oid,
                                team_id=batch.team_id,
                            )
                            verified = transition_step(step, IntegrationStepStatus.VERIFIED, now=self._now())
                            self._save_step(step, verified)
                            self._append(
                                step,
                                JournalBoundary.POSTCHECKED,
                                result_oid=step.integration_commit_oid or decision.observed_head_oid,
                            )
                            current = self._repository.load_batch(batch.batch_id)
                            self._advance_batch(current, step.ordinal + 1)
                        except CoordinatorGitError:
                            results.append(self._mark_manual(batch, "recovery_verification_failed"))
                            continue
                    elif decision.kind is RecoveryDecisionKind.ROLLBACK and step.pre_merge_oid:
                        try:
                            self._append(step, JournalBoundary.ROLLBACK_STARTED, pre_oid=step.pre_merge_oid)
                            await self._git.rollback(binding, pre_oid=step.pre_merge_oid)
                            current_step = self._repository.load_step(step.step_id)
                            rolled = transition_step(
                                current_step,
                                IntegrationStepStatus.ROLLED_BACK,
                                now=self._now(),
                                rollback_oid=step.pre_merge_oid,
                            )
                            self._save_step(current_step, rolled)
                            self._append(rolled, JournalBoundary.ROLLBACK_VERIFIED, result_oid=step.pre_merge_oid)
                        except CoordinatorGitError:
                            results.append(self._mark_manual(batch, "recovery_rollback_failed"))
                            continue
                    elif decision.kind is RecoveryDecisionKind.MANUAL:
                        results.append(self._mark_manual(batch, decision.code))
                        continue
            results.append(await self.execute(batch.batch_id, binding))
        return tuple(results)

    async def _execute_step(
        self,
        batch: IntegrationBatch,
        step: IntegrationStep,
        binding: RepositoryBinding,
    ) -> tuple[IntegrationBatch, IntegrationStep]:
        target = await self._git.target_snapshot(
            binding,
            expected_branch=batch.target_branch,
            require_clean=True,
        )
        if step.ordinal == 0 and target.head_oid != batch.baseline_oid:
            raise CoordinatorGitError("target_baseline_drift", "The target baseline changed before integration.")
        if step.ordinal > 0:
            previous = self._repository.load_step(batch.step_ids[step.ordinal - 1])
            if previous.status is not IntegrationStepStatus.VERIFIED or previous.integration_commit_oid != target.head_oid:
                raise CoordinatorGitError("integration_order_drift", "The preceding integration result is not the target HEAD.")
        if step.expected_target_oid != target.head_oid:
            updated = replace(
                step,
                revision=step.revision + 1,
                expected_target_oid=target.head_oid,
                updated_at=self._now(),
            )
            step = self._save_step(step, updated)
        self._append(step, JournalBoundary.GIT_PRECHECKED, pre_oid=target.head_oid)
        merging = transition_step(
            step,
            IntegrationStepStatus.MERGING,
            now=self._now(),
            pre_merge_oid=target.head_oid,
        )
        step = self._save_step(step, merging)
        self._append(step, JournalBoundary.MERGE_STARTED, pre_oid=target.head_oid)
        await self._git.begin_merge(binding, step, target_branch=batch.target_branch)
        self._append(step, JournalBoundary.MERGE_APPLIED, pre_oid=target.head_oid)
        commit_oid = await self._git.create_integration_commit(
            binding,
            team_id=batch.team_id,
            batch_id=batch.batch_id,
            task_id=step.task_id,
            member_id=step.member_id,
        )
        self._append(step, JournalBoundary.COMMIT_CREATED, pre_oid=target.head_oid, result_oid=commit_oid)
        observed = transition_step(
            step,
            IntegrationStepStatus.COMMIT_OBSERVED,
            now=self._now(),
            integration_commit_oid=commit_oid,
        )
        step = self._save_step(step, observed)
        await self._git.verify_integration_commit(binding, step, commit_oid, team_id=batch.team_id)
        self._append(step, JournalBoundary.POSTCHECKED, result_oid=commit_oid)
        verified = transition_step(step, IntegrationStepStatus.VERIFIED, now=self._now())
        step = self._save_step(step, verified)
        self._append(step, JournalBoundary.COMPLETED, result_oid=commit_oid)
        current = self._repository.load_batch(batch.batch_id)
        batch = self._advance_batch(current, step.ordinal + 1)
        return batch, step

    async def _rollback_failed_step(
        self,
        original: IntegrationStep,
        binding: RepositoryBinding,
        code: str,
    ) -> None:
        step = self._repository.load_step(original.step_id)
        if step.pre_merge_oid is None:
            if not step.status.terminal:
                failed = transition_step(step, IntegrationStepStatus.FAILED, now=self._now(), diagnostic=code)
                self._save_step(step, failed)
            return
        try:
            self._append(step, JournalBoundary.ROLLBACK_STARTED, pre_oid=step.pre_merge_oid, code=code)
            await self._git.rollback(binding, pre_oid=step.pre_merge_oid)
            current = self._repository.load_step(step.step_id)
            rolled = transition_step(
                current,
                IntegrationStepStatus.ROLLED_BACK,
                now=self._now(),
                diagnostic=code,
                rollback_oid=step.pre_merge_oid,
            )
            self._save_step(current, rolled)
            self._append(rolled, JournalBoundary.ROLLBACK_VERIFIED, result_oid=step.pre_merge_oid, code=code)
        except (CoordinatorGitError, TeamValidationError):
            current = self._repository.load_step(step.step_id)
            if not current.status.terminal:
                manual = transition_step(current, IntegrationStepStatus.MANUAL, now=self._now(), diagnostic="rollback_failed")
                self._save_step(current, manual)

    def _mark_manual(self, batch: IntegrationBatch, code: str) -> IntegrationBatch:
        current = self._repository.load_batch(batch.batch_id)
        if current.status.terminal:
            return current
        return self._save_batch(
            current,
            transition_batch(current, IntegrationBatchStatus.MANUAL, now=self._now(), diagnostic=code),
        )

    def _append(
        self,
        step: IntegrationStep,
        boundary: JournalBoundary,
        *,
        pre_oid: str | None = None,
        result_oid: str | None = None,
        code: str | None = None,
    ) -> None:
        journal = self._repository.load_journal(step.step_id)
        self._repository.append_journal(
            step.step_id,
            self._entry(
                boundary,
                task_id=step.task_id,
                pre_oid=pre_oid,
                result_oid=result_oid,
                code=code,
                sequence=len(journal.entries),
            ),
        )

    def _entry(
        self,
        boundary: JournalBoundary,
        *,
        task_id: str | None,
        pre_oid: str | None = None,
        result_oid: str | None = None,
        code: str | None = None,
        sequence: int = 0,
    ) -> CoordinatorJournalEntry:
        return CoordinatorJournalEntry(sequence, boundary, task_id, pre_oid, result_oid, code, self._now())

    def _save_step(self, current: IntegrationStep, candidate: IntegrationStep) -> IntegrationStep:
        return self._repository.update_step(candidate, expected_revision=current.revision)

    def _save_batch(self, current: IntegrationBatch, candidate: IntegrationBatch) -> IntegrationBatch:
        return self._repository.update_batch(candidate, expected_revision=current.revision)

    def _advance_batch(self, current: IntegrationBatch, next_step: int) -> IntegrationBatch:
        if current.next_step >= next_step:
            return current
        return self._save_batch(
            current,
            replace(
                current,
                revision=current.revision + 1,
                next_step=next_step,
                updated_at=self._now(),
            ),
        )

    @staticmethod
    def stable_topology(run: DecompositionRun, include: set[str] | None = None) -> tuple[str, ...]:
        selected = {item.task_id for item in run.tasks} if include is None else set(include)
        specs = {item.task_id: item for item in run.tasks if item.task_id in selected}
        indegree = {task_id: 0 for task_id in specs}
        dependents: dict[str, list[str]] = {task_id: [] for task_id in specs}
        for spec in specs.values():
            for dependency in spec.dependency_task_ids:
                if dependency not in specs:
                    continue
                indegree[spec.task_id] += 1
                dependents[dependency].append(spec.task_id)
        ready = sorted((specs[item].ordinal, item) for item, degree in indegree.items() if degree == 0)
        result: list[str] = []
        while ready:
            _ordinal, task_id = ready.pop(0)
            result.append(task_id)
            for dependent in dependents[task_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append((specs[dependent].ordinal, dependent))
                    ready.sort()
        if len(result) != len(specs):
            raise TeamValidationError("Integration dependencies contain a cycle.")
        return tuple(result)
