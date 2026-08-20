from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable

from .models import (
    MemberQueueEntry,
    MemberWakeReason,
    PlanApprovalRecord,
    PlanApprovalStatus,
    PlanDecision,
    TeamActor,
    TeamActorKind,
    TeamMemberRecord,
    TeamMemberStatus,
    TeamPermissionError,
    TeamState,
    TeamTask,
    TeamTaskStatus,
    TeamTaskView,
    TeamValidationError,
)


_MEMBER_TRANSITIONS: dict[TeamMemberStatus, frozenset[TeamMemberStatus]] = {
    TeamMemberStatus.PROVISIONING: frozenset({TeamMemberStatus.IDLE, TeamMemberStatus.FAILED}),
    TeamMemberStatus.IDLE: frozenset({TeamMemberStatus.QUEUED, TeamMemberStatus.STOPPED}),
    TeamMemberStatus.QUEUED: frozenset({TeamMemberStatus.RUNNING, TeamMemberStatus.STOPPED, TeamMemberStatus.INTERRUPTED, TeamMemberStatus.FAILED}),
    TeamMemberStatus.RUNNING: frozenset({TeamMemberStatus.IDLE, TeamMemberStatus.AWAITING_APPROVAL, TeamMemberStatus.STOPPED, TeamMemberStatus.INTERRUPTED, TeamMemberStatus.FAILED}),
    TeamMemberStatus.AWAITING_APPROVAL: frozenset({TeamMemberStatus.QUEUED, TeamMemberStatus.STOPPED, TeamMemberStatus.FAILED}),
    TeamMemberStatus.STOPPED: frozenset({TeamMemberStatus.QUEUED}),
    TeamMemberStatus.INTERRUPTED: frozenset({TeamMemberStatus.QUEUED, TeamMemberStatus.STOPPED}),
    TeamMemberStatus.FAILED: frozenset({TeamMemberStatus.QUEUED, TeamMemberStatus.STOPPED}),
}


def validate_team_state(state: TeamState) -> None:
    member_names: set[str] = set()
    current_tasks: set[str] = set()
    for member_id, member in state.members.items():
        if member_id != member.member_id or member.name.canonical_key in member_names:
            raise TeamValidationError("Team member identity is inconsistent.")
        member_names.add(member.name.canonical_key)
        if member.current_task_id is not None:
            if member.current_task_id in current_tasks:
                raise TeamValidationError("A task is current for more than one member.")
            current_tasks.add(member.current_task_id)
    for key, registration in state.registry.items():
        if key != registration.participant_name.canonical_key:
            raise TeamValidationError("Mailbox registry key is inconsistent.")
    _validate_dependencies(state.tasks)
    queued = [item.member_id for item in state.queue]
    if len(queued) != len(set(queued)):
        raise TeamValidationError("A member appears more than once in the wake queue.")


def transition_member(
    state: TeamState,
    member_id: str,
    target: TeamMemberStatus,
    *,
    now: datetime,
    active_run_id: str | None = None,
    error: str | None = None,
) -> TeamState:
    member = _member(state, member_id)
    if target is not member.status and target not in _MEMBER_TRANSITIONS[member.status]:
        raise TeamValidationError(f"Illegal member state transition: {member.status.value} -> {target.value}.")
    if target is TeamMemberStatus.RUNNING and not active_run_id:
        raise TeamValidationError("Running members require an active run ID.")
    updated = replace(
        member,
        status=target,
        active_run_id=active_run_id if target is TeamMemberStatus.RUNNING else None,
        run_generation=member.run_generation + (1 if target is TeamMemberStatus.RUNNING else 0),
        last_error=error,
        updated_at=now,
    )
    return _with_member(state, updated, now)


def task_view(state: TeamState, task: TeamTask) -> TeamTaskView:
    blockers = tuple(
        dependency_id
        for dependency_id in task.dependency_ids
        if state.tasks[dependency_id].status is not TeamTaskStatus.COMPLETED
    )
    return TeamTaskView(
        task=task,
        blocked=bool(blockers),
        blocking_task_ids=blockers,
        claimable=(
            task.status is TeamTaskStatus.PENDING
            and task.assignee_id is None
            and not blockers
        ),
    )


def create_task(
    state: TeamState,
    actor: TeamActor,
    *,
    task_id: str,
    title: str,
    description: str,
    dependency_ids: Iterable[str],
    now: datetime,
) -> tuple[TeamState, TeamTaskView]:
    _participant(state, actor)
    if task_id in state.tasks:
        raise TeamValidationError("Task ID already exists.")
    task = TeamTask(
        task_id=task_id,
        revision=0,
        approval_epoch=0,
        title=title,
        description=description,
        status=TeamTaskStatus.PENDING,
        assignee_id=None,
        dependency_ids=tuple(dependency_ids),
        created_by=actor.participant_id,
        result="",
        created_at=now,
        updated_at=now,
    )
    tasks = dict(state.tasks)
    tasks[task_id] = task
    _validate_dependencies(tasks)
    updated = replace(state, tasks=tasks, updated_at=now)
    return updated, task_view(updated, task)


def update_task(
    state: TeamState,
    actor: TeamActor,
    task_id: str,
    *,
    expected_revision: int,
    now: datetime,
    title: str | None = None,
    description: str | None = None,
    dependency_ids: Iterable[str] | None = None,
) -> tuple[TeamState, TeamTaskView]:
    task = _task(state, task_id)
    _check_revision(task, expected_revision)
    if not _can_edit_task(state, actor, task):
        raise TeamPermissionError("Actor may not edit this task.")
    dependencies = task.dependency_ids if dependency_ids is None else tuple(dependency_ids)
    changed_dependencies = dependencies != task.dependency_ids
    updated_task = replace(
        task,
        revision=task.revision + 1,
        approval_epoch=task.approval_epoch + (1 if changed_dependencies else 0),
        title=task.title if title is None else title,
        description=task.description if description is None else description,
        dependency_ids=dependencies,
        updated_at=now,
    )
    tasks = dict(state.tasks)
    tasks[task_id] = updated_task
    _validate_dependencies(tasks)
    updated = replace(state, tasks=tasks, updated_at=now)
    if changed_dependencies:
        updated = invalidate_approvals(updated, task_id, now=now)
    return updated, task_view(updated, updated_task)


def assign_task(
    state: TeamState,
    actor: TeamActor,
    task_id: str,
    member_id: str,
    *,
    expected_revision: int,
    now: datetime,
) -> tuple[TeamState, TeamTaskView]:
    if actor.kind is not TeamActorKind.LEAD:
        raise TeamPermissionError("Only the Team Lead may assign tasks.")
    task = _task(state, task_id)
    _check_revision(task, expected_revision)
    _member(state, member_id)
    members = dict(state.members)
    if task.assignee_id is not None and task.assignee_id in members:
        old = members[task.assignee_id]
        members[old.member_id] = replace(old, current_task_id=None, updated_at=now)
    target = members[member_id]
    if target.current_task_id not in {None, task_id}:
        raise TeamValidationError("Target member already has another current task.")
    members[member_id] = replace(target, current_task_id=task_id, updated_at=now)
    updated_task = replace(
        task,
        revision=task.revision + 1,
        approval_epoch=task.approval_epoch + 1,
        assignee_id=member_id,
        updated_at=now,
    )
    tasks = dict(state.tasks)
    tasks[task_id] = updated_task
    updated = replace(state, members=members, tasks=tasks, updated_at=now)
    updated = invalidate_approvals(updated, task_id, now=now)
    return updated, task_view(updated, updated_task)


def claim_task(
    state: TeamState,
    actor: TeamActor,
    task_id: str,
    *,
    expected_revision: int,
    now: datetime,
) -> tuple[TeamState, TeamTaskView]:
    if actor.kind is not TeamActorKind.MEMBER:
        raise TeamPermissionError("Only a member may claim an unassigned task.")
    task = _task(state, task_id)
    _check_revision(task, expected_revision)
    view = task_view(state, task)
    if not view.claimable:
        raise TeamValidationError("Task is not claimable.")
    member = _member(state, actor.participant_id)
    if member.current_task_id is not None:
        raise TeamValidationError("Member already has a current task.")
    proxy_lead = replace(actor, kind=TeamActorKind.LEAD)
    return assign_task(state, proxy_lead, task_id, member.member_id, expected_revision=expected_revision, now=now)


def transition_task(
    state: TeamState,
    actor: TeamActor,
    task_id: str,
    target: TeamTaskStatus,
    *,
    expected_revision: int,
    result: str,
    now: datetime,
) -> tuple[TeamState, TeamTaskView]:
    task = _task(state, task_id)
    _check_revision(task, expected_revision)
    if actor.kind is not TeamActorKind.LEAD and task.assignee_id != actor.participant_id:
        raise TeamPermissionError("Only the Lead or task assignee may change task status.")
    allowed = {
        TeamTaskStatus.PENDING: {TeamTaskStatus.IN_PROGRESS, TeamTaskStatus.CANCELLED},
        TeamTaskStatus.IN_PROGRESS: {TeamTaskStatus.COMPLETED, TeamTaskStatus.FAILED, TeamTaskStatus.CANCELLED},
        TeamTaskStatus.COMPLETED: {TeamTaskStatus.PENDING},
        TeamTaskStatus.FAILED: {TeamTaskStatus.PENDING},
        TeamTaskStatus.CANCELLED: {TeamTaskStatus.PENDING},
    }
    if target not in allowed[task.status]:
        raise TeamValidationError("Illegal task status transition.")
    if target is TeamTaskStatus.IN_PROGRESS and task_view(state, task).blocked:
        raise TeamValidationError("Blocked task cannot start.")
    terminal = target.terminal
    reset = target is TeamTaskStatus.PENDING and task.status.terminal
    updated_task = replace(
        task,
        revision=task.revision + 1,
        approval_epoch=task.approval_epoch + (1 if reset else 0),
        status=target,
        result=result,
        started_at=now if target is TeamTaskStatus.IN_PROGRESS else (None if reset else task.started_at),
        finished_at=now if terminal else None,
        updated_at=now,
    )
    members = dict(state.members)
    if terminal and task.assignee_id in members:
        member = members[task.assignee_id]
        members[member.member_id] = replace(member, current_task_id=None, updated_at=now)
    tasks = dict(state.tasks)
    tasks[task_id] = updated_task
    updated = replace(state, members=members, tasks=tasks, updated_at=now)
    if reset:
        updated = invalidate_approvals(updated, task_id, now=now)
    return updated, task_view(updated, updated_task)


def delete_task(
    state: TeamState,
    actor: TeamActor,
    task_id: str,
    *,
    expected_revision: int,
    now: datetime,
) -> TeamState:
    task = _task(state, task_id)
    _check_revision(task, expected_revision)
    if task.status is TeamTaskStatus.IN_PROGRESS:
        raise TeamValidationError("An in-progress task cannot be deleted.")
    if any(task_id in candidate.dependency_ids for candidate in state.tasks.values()):
        raise TeamValidationError("A referenced task cannot be deleted.")
    if actor.kind is not TeamActorKind.LEAD and not (
        task.status is TeamTaskStatus.PENDING and task.assignee_id is None
    ):
        raise TeamPermissionError("Actor may not delete this task.")
    tasks = dict(state.tasks)
    del tasks[task_id]
    approvals = {key: value for key, value in state.approvals.items() if value.task_id != task_id}
    return replace(state, tasks=tasks, approvals=approvals, updated_at=now)


def request_approval(
    state: TeamState,
    actor: TeamActor,
    *,
    request_id: str,
    plan_version: int,
    plan_text: str,
    summary: str,
    now: datetime,
) -> tuple[TeamState, PlanApprovalRecord]:
    if actor.kind is not TeamActorKind.MEMBER:
        raise TeamPermissionError("Only a member may request plan approval.")
    member = _member(state, actor.participant_id)
    if not member.requires_approval or member.current_task_id is None:
        raise TeamValidationError("Member does not have an approval-gated current task.")
    task = _task(state, member.current_task_id)
    previous_versions = [
        item.plan_version for item in state.approvals.values()
        if item.member_id == member.member_id and item.task_id == task.task_id
    ]
    expected_version = max(previous_versions, default=0) + 1
    if plan_version != expected_version:
        raise TeamValidationError(f"Plan version must be {expected_version}.")
    updated = invalidate_approvals(state, task.task_id, now=now)
    record = PlanApprovalRecord(
        request_id=request_id,
        member_id=member.member_id,
        task_id=task.task_id,
        task_revision=task.revision,
        approval_epoch=task.approval_epoch,
        plan_version=plan_version,
        plan_text=plan_text,
        summary=summary,
        status=PlanApprovalStatus.PENDING,
        decision=None,
        feedback=None,
        requested_at=now,
    )
    approvals = dict(updated.approvals)
    approvals[request_id] = record
    members = dict(updated.members)
    members[member.member_id] = replace(member, status=TeamMemberStatus.AWAITING_APPROVAL, active_run_id=None, updated_at=now)
    return replace(updated, approvals=approvals, members=members, updated_at=now), record


def decide_approval(
    state: TeamState,
    actor: TeamActor,
    request_id: str,
    decision: PlanDecision,
    *,
    feedback: str | None,
    now: datetime,
) -> tuple[TeamState, PlanApprovalRecord]:
    if actor.kind is not TeamActorKind.LEAD:
        raise TeamPermissionError("Only the Team Lead may decide approvals.")
    try:
        record = state.approvals[request_id]
    except KeyError as exc:
        raise TeamValidationError("Unknown approval request.") from exc
    if record.status is not PlanApprovalStatus.PENDING:
        raise TeamValidationError("Approval request is no longer pending.")
    if decision is PlanDecision.REJECT and not feedback:
        raise TeamValidationError("Rejected plans require feedback.")
    status = PlanApprovalStatus.APPROVED if decision is PlanDecision.APPROVE else PlanApprovalStatus.REJECTED
    decided = replace(record, status=status, decision=decision, feedback=feedback, decided_at=now)
    approvals = dict(state.approvals)
    approvals[request_id] = decided
    return replace(state, approvals=approvals, updated_at=now), decided


def approval_is_valid(state: TeamState, member_id: str, task_id: str) -> bool:
    member = state.members.get(member_id)
    task = state.tasks.get(task_id)
    if member is None or task is None or task.assignee_id != member_id:
        return False
    return any(
        item.status is PlanApprovalStatus.APPROVED
        and item.member_id == member_id
        and item.task_id == task_id
        and item.task_revision == task.revision
        and item.approval_epoch == task.approval_epoch
        for item in state.approvals.values()
    )


def invalidate_approvals(state: TeamState, task_id: str, *, now: datetime) -> TeamState:
    approvals = {
        key: (
            replace(item, status=PlanApprovalStatus.INVALIDATED, decided_at=now)
            if item.task_id == task_id and item.status in {PlanApprovalStatus.PENDING, PlanApprovalStatus.APPROVED}
            else item
        )
        for key, item in state.approvals.items()
    }
    return replace(state, approvals=approvals, updated_at=now)


def enqueue_member(
    state: TeamState,
    member_id: str,
    *,
    queue_id: str,
    reason: MemberWakeReason,
    message_ids: Iterable[str],
    now: datetime,
) -> tuple[TeamState, MemberQueueEntry | None]:
    member = _member(state, member_id)
    if member.status in {TeamMemberStatus.RUNNING, TeamMemberStatus.STOPPED}:
        return state, None
    queue = list(state.queue)
    for index, entry in enumerate(queue):
        if entry.member_id == member_id:
            merged = replace(entry, message_ids=tuple(dict.fromkeys((*entry.message_ids, *message_ids))))
            queue[index] = merged
            return replace(state, queue=tuple(queue), updated_at=now), merged
    sequence = max((item.sequence for item in queue), default=-1) + 1
    entry = MemberQueueEntry(queue_id, sequence, member_id, reason, tuple(message_ids), now)
    queue.append(entry)
    members = dict(state.members)
    members[member_id] = replace(member, status=TeamMemberStatus.QUEUED, updated_at=now)
    return replace(state, queue=tuple(queue), members=members, updated_at=now), entry


def dequeue_member(state: TeamState, member_id: str, *, now: datetime) -> TeamState:
    return replace(state, queue=tuple(item for item in state.queue if item.member_id != member_id), updated_at=now)


def _participant(state: TeamState, actor: TeamActor) -> None:
    if actor.team_id != state.manifest.team_id:
        raise TeamPermissionError("Actor belongs to another team.")
    if actor.kind is TeamActorKind.MEMBER and actor.participant_id not in state.members:
        raise TeamPermissionError("Unknown team member.")


def _member(state: TeamState, member_id: str) -> TeamMemberRecord:
    try:
        return state.members[member_id]
    except KeyError as exc:
        raise TeamValidationError("Unknown team member.") from exc


def _task(state: TeamState, task_id: str) -> TeamTask:
    try:
        return state.tasks[task_id]
    except KeyError as exc:
        raise TeamValidationError("Unknown team task.") from exc


def _check_revision(task: TeamTask, expected: int) -> None:
    if task.revision != expected:
        raise TeamValidationError(
            f"Task revision conflict: expected {expected}, current {task.revision}."
        )


def _can_edit_task(state: TeamState, actor: TeamActor, task: TeamTask) -> bool:
    _participant(state, actor)
    if actor.kind is TeamActorKind.LEAD or task.assignee_id == actor.participant_id:
        return True
    return task.status is TeamTaskStatus.PENDING and task.assignee_id is None


def _validate_dependencies(tasks: dict[str, TeamTask] | object) -> None:
    mapping = dict(tasks)  # type: ignore[arg-type]
    for task in mapping.values():
        if task.task_id in task.dependency_ids:
            raise TeamValidationError("Task cannot depend on itself.")
        if any(item not in mapping for item in task.dependency_ids):
            raise TeamValidationError("Task depends on an unknown task.")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise TeamValidationError("Task dependency graph contains a cycle.")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in mapping[task_id].dependency_ids:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in mapping:
        visit(task_id)


def _with_member(state: TeamState, member: TeamMemberRecord, now: datetime) -> TeamState:
    members = dict(state.members)
    members[member.member_id] = member
    return replace(state, members=members, updated_at=now)
