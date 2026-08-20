from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
import uuid

from . import domain
from .models import (
    SCHEMA_VERSION,
    TeamActor,
    TeamMessage,
    TeamName,
    TeamOutboxEntry,
    TeamProtocol,
    TeamState,
    TeamTaskStatus,
    TeamTaskView,
    TeamValidationError,
)
from .repository import TeamMutationRunner, TeamRepository


class TeamTaskService:
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

    async def create(
        self,
        actor: TeamActor,
        *,
        title: str,
        description: str,
        dependency_ids: Sequence[str] = (),
    ) -> TeamTaskView:
        task_id = self._new_id()

        def transform(state: TeamState) -> TeamState:
            candidate, _view = domain.create_task(
                state, actor, task_id=task_id, title=title, description=description,
                dependency_ids=dependency_ids, now=self._now(),
            )
            return candidate

        committed = self._mutations.run(self._team, lease_fence=actor.lease_fence, transform=transform)
        return domain.task_view(committed, committed.tasks[task_id])

    def get(self, actor: TeamActor, task_id: str) -> TeamTaskView:
        state = self._repository.load(self._team)
        self._validate_actor(state, actor)
        try:
            return domain.task_view(state, state.tasks[task_id])
        except KeyError as exc:
            raise TeamValidationError("Unknown team task.") from exc

    def list(
        self,
        actor: TeamActor,
        *,
        status: TeamTaskStatus | None = None,
        assignee: str | None = None,
    ) -> tuple[TeamTaskView, ...]:
        state = self._repository.load(self._team)
        self._validate_actor(state, actor)
        values = [
            domain.task_view(state, task)
            for task in state.tasks.values()
            if (status is None or task.status is status)
            and (assignee is None or task.assignee_id == assignee)
        ]
        return tuple(sorted(values, key=lambda item: (item.task.created_at, item.task.task_id)))

    async def update(
        self,
        actor: TeamActor,
        task_id: str,
        *,
        expected_revision: int,
        title: str | None = None,
        description: str | None = None,
        dependency_ids: Sequence[str] | None = None,
    ) -> TeamTaskView:
        return self._change(
            actor,
            task_id,
            lambda state: domain.update_task(
                state, actor, task_id, expected_revision=expected_revision, now=self._now(),
                title=title, description=description, dependency_ids=dependency_ids,
            )[0],
        )

    async def assign(
        self,
        actor: TeamActor,
        task_id: str,
        member_name: str,
        *,
        expected_revision: int,
    ) -> TeamTaskView:
        def transform(state: TeamState) -> TeamState:
            member_id = self._member_id(state, member_name)
            candidate, view = domain.assign_task(
                state, actor, task_id, member_id,
                expected_revision=expected_revision, now=self._now(),
            )
            message = self._message(
                state,
                sender_id=actor.participant_id,
                recipient_id=member_id,
                summary=f"Task assigned: {view.task.title}",
                body=view.task.description,
                protocol=TeamProtocol.TASK_ASSIGNMENT,
                payload={
                    "task_id": task_id,
                    "task_revision": view.task.revision,
                    "assigned_by": actor.participant_id,
                },
            )
            return self._append_outbox(candidate, message)

        return self._change(actor, task_id, transform)

    async def claim(
        self,
        actor: TeamActor,
        task_id: str,
        *,
        expected_revision: int,
    ) -> TeamTaskView:
        return self._change(
            actor,
            task_id,
            lambda state: domain.claim_task(
                state, actor, task_id, expected_revision=expected_revision, now=self._now()
            )[0],
        )

    async def transition(
        self,
        actor: TeamActor,
        task_id: str,
        status: TeamTaskStatus,
        *,
        expected_revision: int,
        result: str = "",
    ) -> TeamTaskView:
        def transform(state: TeamState) -> TeamState:
            candidate, view = domain.transition_task(
                state, actor, task_id, status,
                expected_revision=expected_revision, result=result, now=self._now(),
            )
            if not status.terminal:
                return candidate
            lead_id = next(
                (item.participant_id for item in state.registry.values() if item.is_lead),
                None,
            )
            if lead_id is None:
                raise TeamValidationError("Team Lead mailbox registration is missing.")
            message = self._message(
                state,
                sender_id=actor.participant_id,
                recipient_id=lead_id,
                summary=f"Task {status.value}: {view.task.title}",
                body=result,
                protocol=TeamProtocol.TASK_STATUS,
                payload={"task_id": task_id, "task_revision": view.task.revision, "status": status.value},
            )
            return self._append_outbox(candidate, message)

        return self._change(actor, task_id, transform)

    async def delete(
        self,
        actor: TeamActor,
        task_id: str,
        *,
        expected_revision: int,
    ) -> None:
        self._mutations.run(
            self._team,
            lease_fence=actor.lease_fence,
            transform=lambda state: domain.delete_task(
                state, actor, task_id, expected_revision=expected_revision, now=self._now()
            ),
        )

    def _change(
        self,
        actor: TeamActor,
        task_id: str,
        transform: Callable[[TeamState], TeamState],
    ) -> TeamTaskView:
        committed = self._mutations.run(self._team, lease_fence=actor.lease_fence, transform=transform)
        try:
            return domain.task_view(committed, committed.tasks[task_id])
        except KeyError as exc:
            raise TeamValidationError("Task no longer exists.") from exc

    def _message(
        self,
        state: TeamState,
        *,
        sender_id: str,
        recipient_id: str,
        summary: str,
        body: str,
        protocol: TeamProtocol,
        payload: dict[str, object],
    ) -> TeamMessage:
        return TeamMessage(
            schema_version=SCHEMA_VERSION,
            message_id=self._new_id(),
            correlation_id=None,
            sender_id=sender_id,
            recipient_id=recipient_id,
            summary=summary[:256],
            body=body,
            protocol=protocol,
            payload=payload,
            sent_at=self._now(),
        )

    def _append_outbox(self, state: TeamState, message: TeamMessage) -> TeamState:
        entry = TeamOutboxEntry(self._new_id(), message, False, self._now())
        return replace(state, outbox=(*state.outbox, entry), updated_at=self._now())

    @staticmethod
    def _member_id(state: TeamState, member_name: str) -> str:
        canonical = member_name.casefold()
        try:
            registration = state.registry[canonical]
        except KeyError as exc:
            raise TeamValidationError("Unknown team member name.") from exc
        if registration.is_lead or registration.participant_id not in state.members:
            raise TeamValidationError("Target is not an active team member.")
        return registration.participant_id

    @staticmethod
    def _validate_actor(state: TeamState, actor: TeamActor) -> None:
        if actor.team_id != state.manifest.team_id:
            raise TeamValidationError("Actor belongs to another team.")
        if actor.participant_id not in {item.participant_id for item in state.registry.values()}:
            raise TeamValidationError("Actor is not registered in this team.")
