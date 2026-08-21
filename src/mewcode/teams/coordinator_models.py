from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import re

from .models import (
    MAX_DIAGNOSTIC_CHARS,
    MAX_TASK_DEPENDENCIES,
    MAX_TASK_DESCRIPTION_BYTES,
    MAX_TASK_TITLE_CHARS,
    TeamValidationError,
    bounded_text,
    require_absolute,
    require_identifier,
    require_utc,
)


COORDINATOR_SCHEMA_VERSION = 1
COORDINATOR_POLICY_VERSION = 1
MAX_DECOMPOSITION_TASKS = 32
MAX_ACCEPTANCE_CRITERIA = 16
MAX_ACCEPTANCE_CRITERION_CHARS = 1024
MAX_REQUIRED_TOOLS = 32
MAX_USER_GOAL_BYTES = 64 * 1024
MAX_COORDINATOR_DECISIONS = 4096
MAX_COORDINATOR_REVIEWS = MAX_DECOMPOSITION_TASKS
MAX_INTEGRATION_TASKS = 64
MAX_INTEGRATION_COMMITS = 4096
MAX_JOURNAL_ENTRIES = 4096
MAX_BRANCH_CHARS = 256
MAX_EVIDENCE_CHARS = 4096

_HEX_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SAFE_REF_COMPONENT = re.compile(r"^[^\x00-\x20~^:?*\\]+$")


def require_oid(value: str | None, field_name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _HEX_OID.fullmatch(value):
        raise TeamValidationError(f"{field_name} must be a full lowercase Git object ID.")
    return value


def require_branch(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("refs/heads/")
        or len(value) > MAX_BRANCH_CHARS
        or value.endswith(("/", ".", ".lock"))
        or ".." in value
        or "@{" in value
        or "//" in value
        or not _SAFE_REF_COMPONENT.fullmatch(value)
    ):
        raise TeamValidationError("target_branch must be a safe local branch ref.")
    return value


def _bounded_required(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise TeamValidationError(f"{field_name} is invalid.")
    if "\x00" in value:
        raise TeamValidationError(f"{field_name} is invalid.")
    return value


def _tuple_unique(values: tuple[str, ...], field_name: str, limit: int) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) > limit or len(set(result)) != len(result):
        raise TeamValidationError(f"{field_name} is too large or contains duplicates.")
    for item in result:
        require_identifier(item, field_name)
    return result


class DeliveryKind(StrEnum):
    GIT = "git"
    NO_GIT = "no_git"


class DispatchAction(StrEnum):
    PENDING = "pending"
    ASSIGN = "assign"
    REASSIGN = "reassign"
    CANCEL = "cancel"
    STOP = "stop"
    MANUAL = "manual"
    START_FAILED = "start_failed"


class DecompositionStatus(StrEnum):
    PREPARED = "prepared"
    ACTIVE = "active"
    READY_TO_INTEGRATE = "ready_to_integrate"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    MANUAL = "manual"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.CANCELLED, self.FAILED, self.MANUAL}


class DeliveryReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MANUAL = "manual"


class IntegrationBatchStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL = "manual"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.MANUAL}


class IntegrationStepStatus(StrEnum):
    PREPARED = "prepared"
    MERGING = "merging"
    COMMIT_OBSERVED = "commit_observed"
    VERIFIED = "verified"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    MANUAL = "manual"

    @property
    def terminal(self) -> bool:
        return self in {self.VERIFIED, self.ROLLED_BACK, self.FAILED, self.MANUAL}


class JournalBoundary(StrEnum):
    PREPARED = "prepared"
    TEAM_STATE_COMMITTED = "team_state_committed"
    GIT_PRECHECKED = "git_prechecked"
    MERGE_STARTED = "merge_started"
    MERGE_APPLIED = "merge_applied"
    COMMIT_CREATED = "commit_created"
    POSTCHECKED = "postchecked"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_VERIFIED = "rollback_verified"
    MANUAL_REQUIRED = "manual_required"
    COMPLETED = "completed"


class RecoveryDecisionKind(StrEnum):
    RETRY = "retry"
    CONFIRM = "confirm"
    ROLLBACK = "rollback"
    MANUAL = "manual"
    COMPLETE = "complete"


@dataclass(frozen=True)
class CoordinatorSettings:
    schema_version: int
    configuration_enabled: bool
    environment_enabled: bool
    enabled: bool
    safety_policy_version: int
    terminal_backends_verified: bool
    resolved_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != COORDINATOR_SCHEMA_VERSION:
            raise TeamValidationError("Unsupported coordinator settings version.")
        for name in (
            "configuration_enabled",
            "environment_enabled",
            "enabled",
            "terminal_backends_verified",
        ):
            if type(getattr(self, name)) is not bool:
                raise TeamValidationError(f"{name} must be a boolean.")
        if self.enabled != (self.configuration_enabled and self.environment_enabled):
            raise TeamValidationError("Coordinator enabled result does not match both switches.")
        if self.safety_policy_version != COORDINATOR_POLICY_VERSION:
            raise TeamValidationError("Unsupported coordinator safety policy version.")
        object.__setattr__(self, "resolved_at", require_utc(self.resolved_at, "resolved_at"))


@dataclass(frozen=True)
class CoordinatorTaskSpec:
    local_id: str
    task_id: str
    ordinal: int
    title: str
    description: str
    dependency_local_ids: tuple[str, ...]
    dependency_task_ids: tuple[str, ...]
    target_member_id: str | None
    required_role: str | None
    required_tool_names: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    delivery_kind: DeliveryKind

    def __post_init__(self) -> None:
        require_identifier(self.local_id, "local_id")
        require_identifier(self.task_id, "task_id")
        if self.ordinal < 0 or self.ordinal >= MAX_DECOMPOSITION_TASKS:
            raise TeamValidationError("Task ordinal is invalid.")
        _bounded_required(self.title, "title", MAX_TASK_TITLE_CHARS)
        if not isinstance(self.description, str) or len(self.description.encode("utf-8")) > MAX_TASK_DESCRIPTION_BYTES:
            raise TeamValidationError("Task description is invalid.")
        local = _tuple_unique(tuple(self.dependency_local_ids), "dependency_local_ids", MAX_TASK_DEPENDENCIES)
        shared = _tuple_unique(tuple(self.dependency_task_ids), "dependency_task_ids", MAX_TASK_DEPENDENCIES)
        if len(local) != len(shared) or self.local_id in local or self.task_id in shared:
            raise TeamValidationError("Task dependency mapping is invalid.")
        if self.target_member_id is None and self.required_role is None:
            raise TeamValidationError("Task must target a member or require a role.")
        if self.target_member_id is not None:
            require_identifier(self.target_member_id, "target_member_id")
        if self.required_role is not None:
            require_identifier(self.required_role, "required_role")
        tools = _tuple_unique(tuple(self.required_tool_names), "required_tool_names", MAX_REQUIRED_TOOLS)
        criteria = tuple(self.acceptance_criteria)
        if not criteria or len(criteria) > MAX_ACCEPTANCE_CRITERIA or len(set(criteria)) != len(criteria):
            raise TeamValidationError("Acceptance criteria are missing, duplicated, or too numerous.")
        for criterion in criteria:
            _bounded_required(criterion, "acceptance criterion", MAX_ACCEPTANCE_CRITERION_CHARS)
        object.__setattr__(self, "dependency_local_ids", local)
        object.__setattr__(self, "dependency_task_ids", shared)
        object.__setattr__(self, "required_tool_names", tools)
        object.__setattr__(self, "acceptance_criteria", criteria)


@dataclass(frozen=True)
class DispatchDecision:
    decision_id: str
    sequence: int
    task_id: str
    action: DispatchAction
    member_id: str | None
    reason_code: str
    observed_team_revision: int
    worktree_start_oid: str | None
    decided_at: datetime
    reason_summary: str = ""

    def __post_init__(self) -> None:
        require_identifier(self.decision_id, "decision_id")
        require_identifier(self.task_id, "task_id")
        require_identifier(self.reason_code, "reason_code")
        if self.member_id is not None:
            require_identifier(self.member_id, "member_id")
        if self.sequence < 0 or self.observed_team_revision < 0:
            raise TeamValidationError("Dispatch decision counters must not be negative.")
        object.__setattr__(self, "worktree_start_oid", require_oid(self.worktree_start_oid, "worktree_start_oid", optional=True))
        object.__setattr__(self, "decided_at", require_utc(self.decided_at, "decided_at"))
        object.__setattr__(self, "reason_summary", bounded_text(self.reason_summary) or "")


@dataclass(frozen=True)
class DeliveryReview:
    task_id: str
    member_id: str
    task_revision: int
    worktree_start_oid: str | None
    worktree_end_oid: str | None
    commit_oids: tuple[str, ...]
    status: DeliveryReviewStatus
    evidence_summary: str
    reviewed_at: datetime | None

    def __post_init__(self) -> None:
        require_identifier(self.task_id, "task_id")
        require_identifier(self.member_id, "member_id")
        if self.task_revision < 0:
            raise TeamValidationError("Review task revision must not be negative.")
        start = require_oid(self.worktree_start_oid, "worktree_start_oid", optional=True)
        end = require_oid(self.worktree_end_oid, "worktree_end_oid", optional=True)
        commits = tuple(self.commit_oids)
        if len(commits) > MAX_INTEGRATION_COMMITS or len(set(commits)) != len(commits):
            raise TeamValidationError("Review commit range is invalid.")
        for oid in commits:
            require_oid(oid, "commit_oid")
        if bool(commits) != (start is not None and end is not None):
            raise TeamValidationError("Review Git range fields are inconsistent.")
        evidence = self.evidence_summary
        if len(evidence) > MAX_EVIDENCE_CHARS or "\x00" in evidence:
            raise TeamValidationError("Review evidence is invalid.")
        if self.status is DeliveryReviewStatus.ACCEPTED and (not evidence.strip() or self.reviewed_at is None):
            raise TeamValidationError("Accepted reviews require evidence and a review time.")
        if self.reviewed_at is not None:
            object.__setattr__(self, "reviewed_at", require_utc(self.reviewed_at, "reviewed_at"))
        object.__setattr__(self, "worktree_start_oid", start)
        object.__setattr__(self, "worktree_end_oid", end)
        object.__setattr__(self, "commit_oids", commits)


@dataclass(frozen=True)
class DecompositionRun:
    schema_version: int
    revision: int
    run_id: str
    team_id: str
    user_goal: str
    target_branch: str
    target_baseline_oid: str
    auto_integrate: bool
    tasks: tuple[CoordinatorTaskSpec, ...]
    decisions: tuple[DispatchDecision, ...]
    status: DecompositionStatus
    diagnostic: str | None
    created_at: datetime
    updated_at: datetime
    reviews: tuple[DeliveryReview, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != COORDINATOR_SCHEMA_VERSION or self.revision < 0:
            raise TeamValidationError("Decomposition version or revision is invalid.")
        require_identifier(self.run_id, "run_id")
        require_identifier(self.team_id, "team_id")
        if not isinstance(self.user_goal, str) or not self.user_goal.strip() or len(self.user_goal.encode("utf-8")) > MAX_USER_GOAL_BYTES:
            raise TeamValidationError("User goal is invalid or too large.")
        object.__setattr__(self, "target_branch", require_branch(self.target_branch))
        object.__setattr__(self, "target_baseline_oid", require_oid(self.target_baseline_oid, "target_baseline_oid"))
        if type(self.auto_integrate) is not bool:
            raise TeamValidationError("auto_integrate must be a boolean.")
        tasks = tuple(self.tasks)
        if not tasks or len(tasks) > MAX_DECOMPOSITION_TASKS:
            raise TeamValidationError("Decomposition task count is invalid.")
        if [task.ordinal for task in tasks] != list(range(len(tasks))):
            raise TeamValidationError("Decomposition task ordinals must be stable and contiguous.")
        if len({task.local_id for task in tasks}) != len(tasks) or len({task.task_id for task in tasks}) != len(tasks):
            raise TeamValidationError("Decomposition task identities must be unique.")
        by_local = {task.local_id: task for task in tasks}
        by_task = {task.task_id: task for task in tasks}
        for task in tasks:
            expected = tuple(by_local[item].task_id for item in task.dependency_local_ids if item in by_local)
            if len(expected) != len(task.dependency_local_ids) or expected != task.dependency_task_ids:
                raise TeamValidationError("Decomposition dependency mapping is inconsistent.")
        _validate_acyclic(by_task)
        decisions = tuple(self.decisions)
        if len(decisions) > MAX_COORDINATOR_DECISIONS:
            raise TeamValidationError("Decomposition has too many dispatch decisions.")
        if [item.sequence for item in decisions] != list(range(len(decisions))):
            raise TeamValidationError("Dispatch decision sequence is invalid.")
        if any(item.task_id not in by_task for item in decisions):
            raise TeamValidationError("Dispatch decision references an unknown task.")
        reviews = tuple(self.reviews)
        if len(reviews) > MAX_COORDINATOR_REVIEWS or len({item.task_id for item in reviews}) != len(reviews):
            raise TeamValidationError("Delivery reviews are duplicated or too numerous.")
        if any(item.task_id not in by_task for item in reviews):
            raise TeamValidationError("Delivery review references an unknown task.")
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "reviews", reviews)
        object.__setattr__(self, "diagnostic", bounded_text(self.diagnostic))
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True)
class IntegrationBatch:
    schema_version: int
    revision: int
    batch_id: str
    team_id: str
    decomposition_run_id: str
    target_branch: str
    baseline_oid: str
    candidate_task_ids: tuple[str, ...]
    topological_task_ids: tuple[str, ...]
    step_ids: tuple[str, ...]
    next_step: int
    status: IntegrationBatchStatus
    diagnostic: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != COORDINATOR_SCHEMA_VERSION or self.revision < 0:
            raise TeamValidationError("Integration batch version or revision is invalid.")
        for name in ("batch_id", "team_id", "decomposition_run_id"):
            require_identifier(getattr(self, name), name)
        object.__setattr__(self, "target_branch", require_branch(self.target_branch))
        object.__setattr__(self, "baseline_oid", require_oid(self.baseline_oid, "baseline_oid"))
        candidates = _tuple_unique(tuple(self.candidate_task_ids), "candidate_task_ids", MAX_INTEGRATION_TASKS)
        topology = _tuple_unique(tuple(self.topological_task_ids), "topological_task_ids", MAX_INTEGRATION_TASKS)
        steps = _tuple_unique(tuple(self.step_ids), "step_ids", MAX_INTEGRATION_TASKS)
        if set(candidates) != set(topology) or self.next_step < 0 or self.next_step > len(steps):
            raise TeamValidationError("Integration batch ordering or progress is invalid.")
        if self.status is IntegrationBatchStatus.COMPLETED and self.next_step != len(steps):
            raise TeamValidationError("Completed integration batch has unfinished steps.")
        object.__setattr__(self, "candidate_task_ids", candidates)
        object.__setattr__(self, "topological_task_ids", topology)
        object.__setattr__(self, "step_ids", steps)
        object.__setattr__(self, "diagnostic", bounded_text(self.diagnostic))
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True)
class IntegrationStep:
    schema_version: int
    revision: int
    step_id: str
    batch_id: str
    ordinal: int
    task_id: str
    member_id: str
    worktree_root: Path
    member_branch: str
    start_oid: str
    end_oid: str
    commit_oids: tuple[str, ...]
    expected_target_oid: str
    pre_merge_oid: str | None
    integration_commit_oid: str | None
    rollback_oid: str | None
    status: IntegrationStepStatus
    diagnostic: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != COORDINATOR_SCHEMA_VERSION or self.revision < 0 or self.ordinal < 0:
            raise TeamValidationError("Integration step version, revision, or ordinal is invalid.")
        for name in ("step_id", "batch_id", "task_id", "member_id"):
            require_identifier(getattr(self, name), name)
        object.__setattr__(self, "worktree_root", require_absolute(self.worktree_root, "worktree_root"))
        object.__setattr__(self, "member_branch", require_branch(self.member_branch))
        for name in ("start_oid", "end_oid", "expected_target_oid"):
            object.__setattr__(self, name, require_oid(getattr(self, name), name))
        for name in ("pre_merge_oid", "integration_commit_oid", "rollback_oid"):
            object.__setattr__(self, name, require_oid(getattr(self, name), name, optional=True))
        commits = tuple(self.commit_oids)
        if not commits or len(commits) > MAX_INTEGRATION_COMMITS or len(set(commits)) != len(commits):
            raise TeamValidationError("Integration step commit range is invalid.")
        for oid in commits:
            require_oid(oid, "commit_oid")
        if self.status in {IntegrationStepStatus.MERGING, IntegrationStepStatus.COMMIT_OBSERVED, IntegrationStepStatus.VERIFIED} and self.pre_merge_oid is None:
            raise TeamValidationError("Started integration step requires a pre-merge OID.")
        if self.status in {IntegrationStepStatus.COMMIT_OBSERVED, IntegrationStepStatus.VERIFIED} and self.integration_commit_oid is None:
            raise TeamValidationError("Observed integration step requires a commit OID.")
        object.__setattr__(self, "commit_oids", commits)
        object.__setattr__(self, "diagnostic", bounded_text(self.diagnostic))
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True)
class CoordinatorJournalEntry:
    sequence: int
    boundary: JournalBoundary
    task_id: str | None
    pre_oid: str | None
    result_oid: str | None
    diagnostic_code: str | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise TeamValidationError("Journal sequence must not be negative.")
        if self.task_id is not None:
            require_identifier(self.task_id, "task_id")
        if self.diagnostic_code is not None:
            require_identifier(self.diagnostic_code, "diagnostic_code")
        object.__setattr__(self, "pre_oid", require_oid(self.pre_oid, "pre_oid", optional=True))
        object.__setattr__(self, "result_oid", require_oid(self.result_oid, "result_oid", optional=True))
        object.__setattr__(self, "recorded_at", require_utc(self.recorded_at, "recorded_at"))


@dataclass(frozen=True)
class CoordinatorJournal:
    schema_version: int
    revision: int
    journal_id: str
    team_id: str
    operation_kind: str
    operation_id: str
    entries: tuple[CoordinatorJournalEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.schema_version != COORDINATOR_SCHEMA_VERSION or self.revision < 0:
            raise TeamValidationError("Coordinator journal version or revision is invalid.")
        for name in ("journal_id", "team_id", "operation_kind", "operation_id"):
            require_identifier(getattr(self, name), name)
        entries = tuple(self.entries)
        if len(entries) > MAX_JOURNAL_ENTRIES or [item.sequence for item in entries] != list(range(len(entries))):
            raise TeamValidationError("Coordinator journal sequence is invalid.")
        _validate_journal_boundaries(entries)
        object.__setattr__(self, "entries", entries)

    def appended(self, entry: CoordinatorJournalEntry) -> CoordinatorJournal:
        if entry.sequence != len(self.entries):
            raise TeamValidationError("Coordinator journal append sequence is stale.")
        return replace(self, revision=self.revision + 1, entries=(*self.entries, entry))


@dataclass(frozen=True)
class CoordinatorDiagnostic:
    code: str
    message: str
    run_id: str | None = None
    task_id: str | None = None
    batch_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.code, "code")
        for name in ("run_id", "task_id", "batch_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        object.__setattr__(self, "message", bounded_text(self.message, MAX_DIAGNOSTIC_CHARS) or "")


def transition_decomposition(run: DecompositionRun, target: DecompositionStatus, *, now: datetime, diagnostic: str | None = None) -> DecompositionRun:
    allowed = {
        DecompositionStatus.PREPARED: {DecompositionStatus.ACTIVE, DecompositionStatus.FAILED, DecompositionStatus.MANUAL, DecompositionStatus.CANCELLED},
        DecompositionStatus.ACTIVE: {DecompositionStatus.READY_TO_INTEGRATE, DecompositionStatus.FAILED, DecompositionStatus.MANUAL, DecompositionStatus.CANCELLED},
        DecompositionStatus.READY_TO_INTEGRATE: {DecompositionStatus.COMPLETED, DecompositionStatus.FAILED, DecompositionStatus.MANUAL},
        DecompositionStatus.COMPLETED: set(),
        DecompositionStatus.CANCELLED: set(),
        DecompositionStatus.FAILED: set(),
        DecompositionStatus.MANUAL: set(),
    }
    if target is not run.status and target not in allowed[run.status]:
        raise TeamValidationError("Illegal decomposition status transition.")
    return replace(run, revision=run.revision + 1, status=target, diagnostic=diagnostic, updated_at=now)


def transition_batch(batch: IntegrationBatch, target: IntegrationBatchStatus, *, now: datetime, diagnostic: str | None = None, next_step: int | None = None) -> IntegrationBatch:
    allowed = {
        IntegrationBatchStatus.PREPARED: {IntegrationBatchStatus.RUNNING, IntegrationBatchStatus.FAILED, IntegrationBatchStatus.MANUAL},
        IntegrationBatchStatus.RUNNING: {IntegrationBatchStatus.COMPLETED, IntegrationBatchStatus.FAILED, IntegrationBatchStatus.MANUAL},
        IntegrationBatchStatus.COMPLETED: set(),
        IntegrationBatchStatus.FAILED: set(),
        IntegrationBatchStatus.MANUAL: set(),
    }
    if target is not batch.status and target not in allowed[batch.status]:
        raise TeamValidationError("Illegal integration batch status transition.")
    return replace(batch, revision=batch.revision + 1, status=target, diagnostic=diagnostic, next_step=batch.next_step if next_step is None else next_step, updated_at=now)


def transition_step(step: IntegrationStep, target: IntegrationStepStatus, *, now: datetime, diagnostic: str | None = None, **changes: object) -> IntegrationStep:
    allowed = {
        IntegrationStepStatus.PREPARED: {IntegrationStepStatus.MERGING, IntegrationStepStatus.FAILED, IntegrationStepStatus.MANUAL},
        IntegrationStepStatus.MERGING: {IntegrationStepStatus.COMMIT_OBSERVED, IntegrationStepStatus.ROLLED_BACK, IntegrationStepStatus.FAILED, IntegrationStepStatus.MANUAL},
        IntegrationStepStatus.COMMIT_OBSERVED: {IntegrationStepStatus.VERIFIED, IntegrationStepStatus.ROLLED_BACK, IntegrationStepStatus.FAILED, IntegrationStepStatus.MANUAL},
        IntegrationStepStatus.VERIFIED: set(),
        IntegrationStepStatus.ROLLED_BACK: {IntegrationStepStatus.MERGING, IntegrationStepStatus.FAILED, IntegrationStepStatus.MANUAL},
        IntegrationStepStatus.FAILED: set(),
        IntegrationStepStatus.MANUAL: set(),
    }
    if target is not step.status and target not in allowed[step.status]:
        raise TeamValidationError("Illegal integration step status transition.")
    return replace(step, revision=step.revision + 1, status=target, diagnostic=diagnostic, updated_at=now, **changes)


def _validate_acyclic(tasks: dict[str, CoordinatorTaskSpec]) -> None:
    indegree = {task_id: 0 for task_id in tasks}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for task in tasks.values():
        for dependency in task.dependency_task_ids:
            if dependency not in tasks:
                raise TeamValidationError("Coordinator task contains an unknown dependency.")
            indegree[task.task_id] += 1
            dependents[dependency].append(task.task_id)
    ready = sorted((tasks[item].ordinal, item) for item, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        _ordinal, task_id = ready.pop(0)
        visited += 1
        for dependent in dependents[task_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append((tasks[dependent].ordinal, dependent))
                ready.sort()
    if visited != len(tasks):
        raise TeamValidationError("Coordinator task dependencies contain a cycle.")


def _validate_journal_boundaries(entries: tuple[CoordinatorJournalEntry, ...]) -> None:
    if not entries:
        return
    if entries[0].boundary is not JournalBoundary.PREPARED:
        raise TeamValidationError("Coordinator journal must start with prepared.")
    terminal = False
    for previous, current in zip(entries, entries[1:]):
        if terminal:
            raise TeamValidationError("Coordinator journal cannot append after a terminal boundary.")
        if previous.boundary in {JournalBoundary.COMPLETED, JournalBoundary.MANUAL_REQUIRED}:
            terminal = True
            raise TeamValidationError("Coordinator journal cannot append after a terminal boundary.")
        if current.boundary is JournalBoundary.PREPARED:
            raise TeamValidationError("Coordinator journal cannot be prepared twice.")
        if current.boundary is JournalBoundary.ROLLBACK_VERIFIED and previous.boundary is not JournalBoundary.ROLLBACK_STARTED:
            raise TeamValidationError("Rollback verification requires a rollback start boundary.")
