from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import uuid

from . import domain
from .models import (
    PlanApprovalRecord,
    PlanApprovalStatus,
    PlanDecision,
    SCHEMA_VERSION,
    TeamActor,
    TeamActorKind,
    TeamMessage,
    TeamName,
    TeamOutboxEntry,
    TeamPermissionError,
    TeamProtocol,
    TeamState,
    TeamValidationError,
)
from .repository import TeamMutationRunner, TeamRepository


@dataclass(frozen=True)
class ApprovalPermit:
    member_id: str
    task_id: str
    approval_epoch: int
    request_id: str


class TeamApprovalService:
    def __init__(
        self,
        repository: TeamRepository,
        team: TeamName,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._repository = repository
        self._team = team
        self._now = now
        self._new_id = new_id
        self._mutations = TeamMutationRunner(repository)
        self._locks: dict[str, asyncio.Lock] = {}

    async def request(
        self,
        actor: TeamActor,
        *,
        task_id: str,
        plan_version: int,
        plan_text: str,
        summary: str,
    ) -> PlanApprovalRecord:
        request_id = self._new_id()

        def transform(state: TeamState) -> TeamState:
            member = state.members.get(actor.participant_id)
            if member is None or member.current_task_id != task_id:
                raise TeamValidationError("Approval request does not match the member current task.")
            candidate, record = domain.request_approval(
                state, actor, request_id=request_id, plan_version=plan_version,
                plan_text=plan_text, summary=summary, now=self._now(),
            )
            lead_id = next((item.participant_id for item in state.registry.values() if item.is_lead), None)
            if lead_id is None:
                raise TeamValidationError("Team Lead mailbox is missing.")
            message = self._message(
                actor.participant_id, lead_id, summary, plan_text,
                TeamProtocol.PLAN_REQUEST,
                {
                    "request_id": request_id,
                    "task_id": task_id,
                    "task_revision": record.task_revision,
                    "approval_epoch": record.approval_epoch,
                    "plan_version": plan_version,
                },
            )
            return self._outbox(candidate, message)

        committed = self._mutations.run(self._team, lease_fence=actor.lease_fence, transform=transform)
        return committed.approvals[request_id]

    async def decide(
        self,
        actor: TeamActor,
        *,
        request_id: str,
        decision: PlanDecision,
        feedback: str | None,
    ) -> PlanApprovalRecord:
        def transform(state: TeamState) -> TeamState:
            candidate, record = domain.decide_approval(
                state, actor, request_id, decision, feedback=feedback, now=self._now()
            )
            message = self._message(
                actor.participant_id,
                record.member_id,
                f"Plan {decision.value}: {record.summary}",
                feedback or "Approved.",
                TeamProtocol.PLAN_DECISION,
                {
                    "request_id": request_id,
                    "task_id": record.task_id,
                    "plan_version": record.plan_version,
                    "decision": decision.value,
                    "feedback": feedback or "",
                },
            )
            return self._outbox(candidate, message)

        committed = self._mutations.run(self._team, lease_fence=actor.lease_fence, transform=transform)
        return committed.approvals[request_id]

    async def invalidate_for_task(
        self,
        task_id: str,
        *,
        reason: str,
        lease_fence: tuple[str, int],
    ) -> tuple[PlanApprovalRecord, ...]:
        state = self._repository.load(self._team)
        member_id = state.tasks[task_id].assignee_id or f"task:{task_id}"
        async with self._lock(member_id):
            committed = self._mutations.run(
                self._team,
                lease_fence=lease_fence,
                transform=lambda current: domain.invalidate_approvals(current, task_id, now=self._now()),
            )
            return tuple(item for item in committed.approvals.values() if item.task_id == task_id)

    @asynccontextmanager
    async def side_effect_permit(
        self,
        actor: TeamActor,
        task_id: str,
    ) -> AsyncIterator[ApprovalPermit]:
        if actor.kind is not TeamActorKind.MEMBER:
            raise TeamPermissionError("Approval permits are only issued to team members.")
        async with self._lock(actor.participant_id):
            state = self._repository.load(self._team)
            member = state.members.get(actor.participant_id)
            task = state.tasks.get(task_id)
            if member is None or task is None or member.current_task_id != task_id:
                raise TeamPermissionError("Member does not own the current task.")
            if member.requires_approval:
                records = [
                    item for item in state.approvals.values()
                    if item.member_id == member.member_id
                    and item.task_id == task_id
                    and item.status.value == "approved"
                    and item.task_revision == task.revision
                    and item.approval_epoch == task.approval_epoch
                ]
                if not records:
                    raise TeamPermissionError("Current task plan has not been approved.")
                current = max(records, key=lambda item: item.plan_version)
            else:
                current = PlanApprovalRecord(
                    request_id="not-required",
                    member_id=member.member_id,
                    task_id=task_id,
                    task_revision=task.revision,
                    approval_epoch=task.approval_epoch,
                    plan_version=0,
                    plan_text="Approval is not required.",
                    summary="Approval not required",
                    status=PlanApprovalStatus.APPROVED,
                    decision=PlanDecision.APPROVE,
                    feedback=None,
                    requested_at=self._now(),
                    decided_at=self._now(),
                )
            yield ApprovalPermit(member.member_id, task_id, task.approval_epoch, current.request_id)

    def _lock(self, member_id: str) -> asyncio.Lock:
        return self._locks.setdefault(member_id, asyncio.Lock())

    def _message(
        self,
        sender_id: str,
        recipient_id: str,
        summary: str,
        body: str,
        protocol: TeamProtocol,
        payload: dict[str, object],
    ) -> TeamMessage:
        return TeamMessage(
            SCHEMA_VERSION, self._new_id(), None, sender_id, recipient_id,
            summary[:256], body, protocol, payload, self._now(),
        )

    def _outbox(self, state: TeamState, message: TeamMessage) -> TeamState:
        entry = TeamOutboxEntry(self._new_id(), message, False, self._now())
        return replace(state, outbox=(*state.outbox, entry), updated_at=self._now())
