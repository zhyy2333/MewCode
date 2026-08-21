from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import uuid

from .coordinator_git import CoordinatorGitBackend, CoordinatorGitError
from .coordinator_models import (
    COORDINATOR_SCHEMA_VERSION,
    MAX_DECOMPOSITION_TASKS,
    CoordinatorJournal,
    CoordinatorJournalEntry,
    CoordinatorSettings,
    CoordinatorTaskSpec,
    DecompositionRun,
    DecompositionStatus,
    DeliveryKind,
    DeliveryReview,
    DeliveryReviewStatus,
    DispatchAction,
    DispatchDecision,
    IntegrationBatchStatus,
    JournalBoundary,
    transition_decomposition,
)
from .coordinator_repository import CoordinatorRepository
from .integration import TeamIntegrationService
from .mailbox import TeamMailboxService
from .models import (
    TeamActor,
    TeamActorKind,
    TeamMemberBackend,
    TeamMemberRecord,
    TeamMemberStatus,
    TeamName,
    TeamTaskStatus,
    TeamValidationError,
)
from .repository import TeamRepository
from .scheduler import TeamMemberScheduler
from .tasks import TeamTaskService


@dataclass(frozen=True)
class CoordinatorTaskDraft:
    local_id: str
    title: str
    description: str
    dependency_local_ids: tuple[str, ...]
    target_member_id: str | None
    required_role: str | None
    required_tool_names: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    delivery_kind: DeliveryKind = DeliveryKind.GIT


@dataclass(frozen=True)
class DecompositionRequest:
    user_goal: str
    target_branch: str
    tasks: tuple[CoordinatorTaskDraft, ...]
    auto_integrate: bool = False


@dataclass(frozen=True)
class CoordinatorSnapshot:
    enabled: bool
    runs: tuple[DecompositionRun, ...]
    active_member_ids: tuple[str, ...]
    reserved_member_ids: tuple[str, ...]


class TeamDeliveryCoordinator:
    def __init__(
        self,
        settings: CoordinatorSettings,
        state_repository: TeamRepository,
        repository: CoordinatorRepository,
        team: TeamName,
        actor: TeamActor,
        tasks: TeamTaskService,
        mailbox: TeamMailboxService,
        scheduler: TeamMemberScheduler,
        git: CoordinatorGitBackend,
        integration: TeamIntegrationService,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_seconds: float = 2.0,
    ) -> None:
        if not settings.enabled:
            raise TeamValidationError("A delivery coordinator requires both enable switches.")
        if actor.kind is not TeamActorKind.LEAD:
            raise TeamValidationError("A delivery coordinator must be owned by the Team Lead.")
        self.settings = settings
        self._states = state_repository
        self._repository = repository
        self._team = team
        self._actor = actor
        self._tasks = tasks
        self._mailbox = mailbox
        self._scheduler = scheduler
        self._git = git
        self._integration = integration
        self._now = now
        self._new_id = new_id
        self._sleep = sleep
        self._interval = interval_seconds
        self._loop: asyncio.Task[None] | None = None
        self._closed = False
        self._cycle_lock = asyncio.Lock()

    async def open(self) -> None:
        if self._closed:
            raise TeamValidationError("Delivery coordinator is closed.")
        if self._loop is not None:
            return
        state = self._states.load(self._team)
        await self._integration.recover(state.manifest.repository)
        await self.recover_decompositions()
        self._loop = asyncio.create_task(self._run_loop())

    async def close(self) -> None:
        self._closed = True
        task, self._loop = self._loop, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def snapshot(self) -> CoordinatorSnapshot:
        return CoordinatorSnapshot(
            True,
            self._repository.list_decompositions(),
            tuple(sorted(self._scheduler.active_member_ids)),
            tuple(sorted(self._scheduler.reserved_member_ids)),
        )

    def inspect_delivery(self, run_id: str):
        return self._repository.load_decomposition(run_id).reviews

    def integration_status(self):
        return self._repository.list_batches()

    async def plan_integration(self, run_id: str):
        run = self._repository.load_decomposition(run_id)
        if run.status is not DecompositionStatus.READY_TO_INTEGRATE:
            raise TeamValidationError("Decomposition is not ready for integration.")
        state = self._states.load(self._team)
        run = await self._refresh_reviews(run, state)
        if (
            len(run.reviews) != len(run.tasks)
            or any(item.status is not DeliveryReviewStatus.ACCEPTED for item in run.reviews)
        ):
            manual = transition_decomposition(
                run,
                DecompositionStatus.MANUAL,
                now=self._now(),
                diagnostic="delivery_changed_before_integration",
            )
            self._repository.update_decomposition(manual, expected_revision=run.revision)
            raise TeamValidationError("A delivery review changed before integration planning.")
        return self._integration.plan(run, state)

    async def integrate(self, batch_id: str):
        state = self._states.load(self._team)
        return await self._integration.execute(batch_id, state.manifest.repository)

    async def recover_git(self):
        state = self._states.load(self._team)
        return await self._integration.recover(state.manifest.repository)

    async def decompose(self, request: DecompositionRequest) -> DecompositionRun:
        if not request.tasks or len(request.tasks) > MAX_DECOMPOSITION_TASKS:
            raise TeamValidationError("Coordinator decomposition task count is invalid.")
        state = self._states.load(self._team)
        target = await self._git.target_snapshot(
            state.manifest.repository,
            expected_branch=request.target_branch,
            require_clean=True,
        )
        run_id = self._new_id()
        drafts = tuple(request.tasks)
        if len({item.local_id for item in drafts}) != len(drafts):
            raise TeamValidationError("Coordinator task local IDs must be unique.")
        task_ids = {item.local_id: self._new_id() for item in drafts}
        if any(item not in task_ids for draft in drafts for item in draft.dependency_local_ids):
            raise TeamValidationError("Coordinator task references an unknown dependency.")
        specs = tuple(
            CoordinatorTaskSpec(
                draft.local_id,
                task_ids[draft.local_id],
                ordinal,
                draft.title,
                draft.description,
                tuple(draft.dependency_local_ids),
                tuple(task_ids[item] for item in draft.dependency_local_ids),
                draft.target_member_id,
                draft.required_role,
                tuple(draft.required_tool_names),
                tuple(draft.acceptance_criteria),
                draft.delivery_kind,
            )
            for ordinal, draft in enumerate(drafts)
        )
        created_at = self._now()
        run = DecompositionRun(
            COORDINATOR_SCHEMA_VERSION,
            0,
            run_id,
            state.manifest.team_id,
            request.user_goal,
            request.target_branch,
            target.head_oid,
            request.auto_integrate,
            specs,
            (),
            DecompositionStatus.PREPARED,
            None,
            created_at,
            created_at,
        )
        journal = CoordinatorJournal(
            COORDINATOR_SCHEMA_VERSION,
            0,
            run_id,
            state.manifest.team_id,
            "decomposition",
            run_id,
            (self._entry(JournalBoundary.PREPARED),),
        )
        self._repository.create_decomposition(run)
        self._repository.create_journal(journal)
        try:
            await self._tasks.create_batch(self._actor, specs)
            self._append_run(run, JournalBoundary.TEAM_STATE_COMMITTED)
            active = transition_decomposition(run, DecompositionStatus.ACTIVE, now=self._now())
            active = self._repository.update_decomposition(active, expected_revision=run.revision)
            self._append_run(active, JournalBoundary.COMPLETED)
            return active
        except BaseException as exc:
            code = "task_publish_failed"
            try:
                current = self._repository.load_decomposition(run_id)
                if not current.status.terminal:
                    failed = transition_decomposition(current, DecompositionStatus.FAILED, now=self._now(), diagnostic=code)
                    self._repository.update_decomposition(failed, expected_revision=current.revision)
            except Exception:
                pass
            raise TeamValidationError("Coordinator task publication failed.") from exc

    async def recover_decompositions(self) -> tuple[DecompositionRun, ...]:
        recovered: list[DecompositionRun] = []
        state = self._states.load(self._team)
        for run in self._repository.list_decompositions(active_only=True):
            if run.status is not DecompositionStatus.PREPARED:
                continue
            present = [item for item in run.tasks if item.task_id in state.tasks]
            if not present:
                await self._tasks.create_batch(self._actor, run.tasks)
            elif len(present) != len(run.tasks) or not self._batch_matches(state, run):
                manual = transition_decomposition(
                    run, DecompositionStatus.MANUAL, now=self._now(), diagnostic="partial_task_publication",
                )
                recovered.append(self._repository.update_decomposition(manual, expected_revision=run.revision))
                continue
            self._append_run(run, JournalBoundary.TEAM_STATE_COMMITTED)
            active = transition_decomposition(run, DecompositionStatus.ACTIVE, now=self._now())
            recovered.append(self._repository.update_decomposition(active, expected_revision=run.revision))
        return tuple(recovered)

    async def reconcile(self, run_id: str | None = None) -> tuple[DecompositionRun, ...]:
        async with self._cycle_lock:
            runs = (
                (self._repository.load_decomposition(run_id),)
                if run_id is not None
                else self._repository.list_decompositions(active_only=True)
            )
            results: list[DecompositionRun] = []
            for run in runs:
                if run.status is DecompositionStatus.ACTIVE:
                    run = await self._reconcile_run(run)
                if run.status is DecompositionStatus.READY_TO_INTEGRATE and run.auto_integrate:
                    run = await self._auto_integrate(run)
                results.append(run)
            return tuple(results)

    async def review(
        self,
        run_id: str,
        task_id: str,
        status: DeliveryReviewStatus,
        *,
        evidence: str,
    ) -> DecompositionRun:
        if status is DeliveryReviewStatus.PENDING:
            raise TeamValidationError("Lead review must select an outcome.")
        with self._repository.task_lock(task_id):
            run = self._repository.load_decomposition(run_id)
            reviews = {item.task_id: item for item in run.reviews}
            review = reviews.get(task_id)
            if review is None:
                raise TeamValidationError("No frozen delivery is available for review.")
            reviews[task_id] = replace(
                review,
                status=status,
                evidence_summary=evidence,
                reviewed_at=self._now(),
            )
            candidate = replace(
                run,
                revision=run.revision + 1,
                reviews=tuple(reviews[item.task_id] for item in run.tasks if item.task_id in reviews),
                updated_at=self._now(),
            )
            return self._repository.update_decomposition(candidate, expected_revision=run.revision)

    async def decide(
        self,
        run_id: str,
        task_id: str,
        action: DispatchAction,
        *,
        member_id: str | None = None,
        reason_code: str,
        reason: str,
    ) -> DecompositionRun:
        if action not in {DispatchAction.REASSIGN, DispatchAction.CANCEL, DispatchAction.STOP, DispatchAction.MANUAL}:
            raise TeamValidationError("Unsupported manual coordinator decision.")
        with self._repository.task_lock(task_id):
            run = self._repository.load_decomposition(run_id)
            state = self._states.load(self._team)
            task = state.tasks[task_id]
            target_id = member_id or task.assignee_id
            if action is DispatchAction.REASSIGN:
                if member_id is None or member_id not in state.members:
                    raise TeamValidationError("Reassignment requires an active member.")
                await self._tasks.assign(
                    self._actor, task_id, state.members[member_id].name.value,
                    expected_revision=task.revision,
                )
                await self._mailbox.flush_outbox()
            elif action is DispatchAction.CANCEL:
                if not task.status.terminal:
                    await self._tasks.transition(
                        self._actor, task_id, TeamTaskStatus.CANCELLED,
                        expected_revision=task.revision, result=reason,
                    )
            elif action is DispatchAction.STOP:
                if target_id is None:
                    raise TeamValidationError("Stop requires an assigned member.")
                await self._scheduler.stop(target_id)
            elif action is DispatchAction.MANUAL:
                manual = transition_decomposition(run, DecompositionStatus.MANUAL, now=self._now(), diagnostic=reason_code)
                run = self._repository.update_decomposition(manual, expected_revision=run.revision)
            return self._record_decision(run, task_id, action, target_id, reason_code, reason, None)

    async def _reconcile_run(self, initial: DecompositionRun) -> DecompositionRun:
        run = initial
        state = self._states.load(self._team)
        for spec in run.tasks:
            task = state.tasks[spec.task_id]
            if task.status is TeamTaskStatus.PENDING and task.assignee_id is None:
                if any(state.tasks[item].status is not TeamTaskStatus.COMPLETED for item in spec.dependency_task_ids):
                    run = self._record_pending_once(run, spec.task_id, "dependencies_blocked")
                    continue
                eligible = self._eligible_members(state, spec, run)
                if not eligible:
                    run = self._record_pending_once(
                        run,
                        spec.task_id,
                        self._ineligibility_code(state, spec),
                    )
                    continue
                member = eligible[0]
                with self._repository.task_lock(spec.task_id):
                    reservation = await self._scheduler.try_reserve(member.member_id)
                    if reservation is None:
                        run = self._record_pending_once(run, spec.task_id, "capacity_unavailable")
                        continue
                    try:
                        start_oid, _branch, _root = await self._git.member_head(
                            state.manifest.repository, state.manifest.team_id, member,
                        )
                        view = await self._tasks.assign(
                            self._actor,
                            spec.task_id,
                            member.name.value,
                            expected_revision=task.revision,
                        )
                        run = self._record_decision(
                            run, spec.task_id, DispatchAction.ASSIGN, member.member_id,
                            "assigned", "Task assigned by coordinator.", start_oid,
                        )
                        await self._mailbox.flush_outbox()
                        task = view.task
                    except BaseException:
                        await self._scheduler.release_reservation(reservation)
                        raise
                state = self._states.load(self._team)

            task = state.tasks[spec.task_id]
            if task.status is TeamTaskStatus.COMPLETED and not any(item.task_id == task.task_id for item in run.reviews):
                review = await self._freeze_delivery(run, spec, state)
                if review is not None:
                    run = replace(
                        run,
                        revision=run.revision + 1,
                        reviews=(*run.reviews, review),
                        updated_at=self._now(),
                    )
                    run = self._repository.update_decomposition(run, expected_revision=run.revision - 1)

        state = self._states.load(self._team)
        run = await self._refresh_reviews(run, state)
        statuses = [state.tasks[item.task_id].status for item in run.tasks]
        if any(item in {TeamTaskStatus.FAILED, TeamTaskStatus.CANCELLED} for item in statuses):
            failed = transition_decomposition(run, DecompositionStatus.FAILED, now=self._now(), diagnostic="task_failed")
            return self._repository.update_decomposition(failed, expected_revision=run.revision)
        reviews = {item.task_id: item for item in run.reviews}
        if all(item is TeamTaskStatus.COMPLETED for item in statuses) and len(reviews) == len(run.tasks):
            if any(item.status in {DeliveryReviewStatus.REJECTED, DeliveryReviewStatus.MANUAL} for item in reviews.values()):
                manual = transition_decomposition(run, DecompositionStatus.MANUAL, now=self._now(), diagnostic="review_not_accepted")
                return self._repository.update_decomposition(manual, expected_revision=run.revision)
            if all(item.status is DeliveryReviewStatus.ACCEPTED for item in reviews.values()):
                ready = transition_decomposition(run, DecompositionStatus.READY_TO_INTEGRATE, now=self._now())
                return self._repository.update_decomposition(ready, expected_revision=run.revision)
        return run

    async def _freeze_delivery(
        self,
        run: DecompositionRun,
        spec: CoordinatorTaskSpec,
        state,
    ) -> DeliveryReview | None:
        task = state.tasks[spec.task_id]
        if task.assignee_id is None:
            return None
        member = state.members[task.assignee_id]
        if (
            member.active_run_id is not None
            or member.status in {TeamMemberStatus.PROVISIONING, TeamMemberStatus.QUEUED, TeamMemberStatus.RUNNING}
            or member.member_id in self._scheduler.active_member_ids
            or member.member_id in self._scheduler.reserved_member_ids
        ):
            return None
        decision = next(
            (item for item in reversed(run.decisions) if item.task_id == task.task_id and item.action in {DispatchAction.ASSIGN, DispatchAction.REASSIGN}),
            None,
        )
        if spec.delivery_kind is DeliveryKind.NO_GIT:
            return DeliveryReview(
                task.task_id, member.member_id, task.revision, None, None, (),
                DeliveryReviewStatus.PENDING, "", None,
            )
        if decision is None or decision.worktree_start_oid is None:
            return None
        try:
            snapshot = await self._git.inspect_member(
                state.manifest.repository,
                state.manifest.team_id,
                member,
                start_oid=decision.worktree_start_oid,
            )
        except CoordinatorGitError:
            return None
        return DeliveryReview(
            task.task_id,
            member.member_id,
            task.revision,
            snapshot.start_oid,
            snapshot.end_oid,
            snapshot.commit_oids,
            DeliveryReviewStatus.PENDING,
            "",
            None,
        )

    async def _refresh_reviews(self, run: DecompositionRun, state) -> DecompositionRun:
        specs = {item.task_id: item for item in run.tasks}
        refreshed: list[DeliveryReview] = []
        for review in run.reviews:
            task = state.tasks.get(review.task_id)
            member = state.members.get(review.member_id)
            spec = specs[review.task_id]
            if (
                task is None
                or member is None
                or task.status is not TeamTaskStatus.COMPLETED
                or task.revision != review.task_revision
                or task.assignee_id != review.member_id
            ):
                continue
            if spec.delivery_kind is DeliveryKind.NO_GIT:
                refreshed.append(review)
                continue
            if review.worktree_start_oid is None:
                continue
            try:
                snapshot = await self._git.inspect_member(
                    state.manifest.repository,
                    state.manifest.team_id,
                    member,
                    start_oid=review.worktree_start_oid,
                )
            except CoordinatorGitError:
                continue
            if snapshot.end_oid == review.worktree_end_oid and snapshot.commit_oids == review.commit_oids:
                refreshed.append(review)
            else:
                refreshed.append(
                    DeliveryReview(
                        review.task_id,
                        review.member_id,
                        review.task_revision,
                        snapshot.start_oid,
                        snapshot.end_oid,
                        snapshot.commit_oids,
                        DeliveryReviewStatus.PENDING,
                        "",
                        None,
                    )
                )
        values = tuple(refreshed)
        if values == run.reviews:
            return run
        candidate = replace(
            run,
            revision=run.revision + 1,
            reviews=values,
            updated_at=self._now(),
        )
        return self._repository.update_decomposition(candidate, expected_revision=run.revision)

    async def _auto_integrate(self, run: DecompositionRun) -> DecompositionRun:
        state = self._states.load(self._team)
        if not any(item.delivery_kind is DeliveryKind.GIT for item in run.tasks):
            completed_run = transition_decomposition(run, DecompositionStatus.COMPLETED, now=self._now())
            return self._repository.update_decomposition(completed_run, expected_revision=run.revision)
        batches = [item for item in self._repository.list_batches() if item.decomposition_run_id == run.run_id]
        batch = batches[0] if batches else self._integration.plan(run, state)
        completed = await self._integration.execute(batch.batch_id, state.manifest.repository)
        target = (
            DecompositionStatus.COMPLETED
            if completed.status is IntegrationBatchStatus.COMPLETED
            else DecompositionStatus.FAILED
        )
        updated = transition_decomposition(
            run,
            target,
            now=self._now(),
            diagnostic=completed.diagnostic,
        )
        return self._repository.update_decomposition(updated, expected_revision=run.revision)

    def _eligible_members(
        self,
        state,
        spec: CoordinatorTaskSpec,
        run: DecompositionRun,
    ) -> tuple[TeamMemberRecord, ...]:
        assignment_count = {
            member_id: sum(1 for item in run.decisions if item.member_id == member_id and item.action in {DispatchAction.ASSIGN, DispatchAction.REASSIGN})
            for member_id in state.members
        }
        values = []
        for member in state.members.values():
            if spec.target_member_id is not None and member.member_id != spec.target_member_id:
                continue
            if spec.required_role is not None and member.role.role_name != spec.required_role:
                continue
            if not set(spec.required_tool_names) <= set(member.role.allowed_tool_names):
                continue
            if member.status is not TeamMemberStatus.IDLE or member.current_task_id is not None or member.active_run_id is not None:
                continue
            if member.member_id in self._scheduler.active_member_ids:
                continue
            if not self.settings.terminal_backends_verified and member.backend is not TeamMemberBackend.IN_PROCESS:
                continue
            values.append(member)
        return tuple(sorted(values, key=lambda item: (assignment_count[item.member_id], item.created_at, item.member_id)))

    def _record_pending_once(self, run: DecompositionRun, task_id: str, code: str) -> DecompositionRun:
        if run.decisions and run.decisions[-1].task_id == task_id and run.decisions[-1].action is DispatchAction.PENDING and run.decisions[-1].reason_code == code:
            return run
        return self._record_decision(run, task_id, DispatchAction.PENDING, None, code, "Task remains pending.", None)

    def _ineligibility_code(self, state, spec: CoordinatorTaskSpec) -> str:
        if not self.settings.terminal_backends_verified:
            matching = [
                member
                for member in state.members.values()
                if (spec.target_member_id is None or member.member_id == spec.target_member_id)
                and (spec.required_role is None or member.role.role_name == spec.required_role)
                and set(spec.required_tool_names) <= set(member.role.allowed_tool_names)
            ]
            if matching and all(item.backend is not TeamMemberBackend.IN_PROCESS for item in matching):
                return "terminal_backends_unverified"
        return "no_eligible_member"

    def _record_decision(
        self,
        run: DecompositionRun,
        task_id: str,
        action: DispatchAction,
        member_id: str | None,
        reason_code: str,
        reason: str,
        start_oid: str | None,
    ) -> DecompositionRun:
        state = self._states.load(self._team)
        decision = DispatchDecision(
            self._new_id(), len(run.decisions), task_id, action, member_id, reason_code,
            state.revision, start_oid, self._now(), reason,
        )
        candidate = replace(
            run,
            revision=run.revision + 1,
            decisions=(*run.decisions, decision),
            updated_at=self._now(),
        )
        return self._repository.update_decomposition(candidate, expected_revision=run.revision)

    def _append_run(self, run: DecompositionRun, boundary: JournalBoundary) -> None:
        journal = self._repository.load_journal(run.run_id)
        if any(item.boundary is boundary for item in journal.entries):
            return
        self._repository.append_journal(
            run.run_id,
            self._entry(boundary, sequence=len(journal.entries)),
        )

    def _entry(self, boundary: JournalBoundary, *, sequence: int = 0) -> CoordinatorJournalEntry:
        return CoordinatorJournalEntry(sequence, boundary, None, None, None, None, self._now())

    @staticmethod
    def _batch_matches(state, run: DecompositionRun) -> bool:
        for spec in run.tasks:
            task = state.tasks.get(spec.task_id)
            if task is None or task.title != spec.title or task.description != spec.description or task.dependency_ids != spec.dependency_task_ids:
                return False
        return True

    async def _run_loop(self) -> None:
        while not self._closed:
            try:
                await self._sleep(self._interval)
                await self.reconcile()
            except asyncio.CancelledError:
                return
            except Exception:
                # Persisted state remains authoritative; the next explicit reconcile can report it.
                continue
