from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
import uuid

from .codec import encode_json
from . import domain
from .models import (
    MAX_PROTOCOL_PAYLOAD_BYTES,
    MemberWakeReason,
    PlanDecision,
    ProtocolTransition,
    SCHEMA_VERSION,
    TeamActor,
    TeamActorKind,
    TeamMessage,
    TeamMessageDraft,
    TeamName,
    TeamOutboxEntry,
    TeamProtocol,
    TeamState,
    TeamTaskStatus,
    TeamValidationError,
)
from .repository import TeamRepository


_PAYLOAD_FIELDS: dict[TeamProtocol, Mapping[str, type]] = {
    TeamProtocol.TEXT: {},
    TeamProtocol.TASK_ASSIGNMENT: {"task_id": str, "task_revision": int, "assigned_by": str},
    TeamProtocol.TASK_STATUS: {"task_id": str, "task_revision": int, "status": str},
    TeamProtocol.PLAN_REQUEST: {
        "request_id": str,
        "task_id": str,
        "task_revision": int,
        "approval_epoch": int,
        "plan_version": int,
    },
    TeamProtocol.PLAN_DECISION: {
        "request_id": str,
        "task_id": str,
        "plan_version": int,
        "decision": str,
        "feedback": str,
    },
    TeamProtocol.MEMBER_IDLE: {
        "member_id": str,
        "task_id": str,
        "task_status": str,
        "result_summary": str,
    },
    TeamProtocol.STOP_REQUEST: {"member_id": str, "reason": str},
}


class TeamProtocolRouter:
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

    async def prepare(self, actor: TeamActor, draft: TeamMessageDraft) -> ProtocolTransition:
        state = self._repository.load(self._team)
        if actor.team_id != state.manifest.team_id:
            raise TeamValidationError("Message actor belongs to another team.")
        sender = self._registration_for_id(state, actor.participant_id)
        recipient = self._registration_for_name(state, draft.recipient)
        payload = self._validate_payload(draft.protocol, draft.payload)
        self._validate_direction(state, actor, sender.is_lead, recipient.is_lead, recipient.participant_id, draft.protocol, payload)
        message = TeamMessage(
            schema_version=SCHEMA_VERSION,
            message_id=draft.message_id or self._new_id(),
            correlation_id=draft.correlation_id,
            sender_id=actor.participant_id,
            recipient_id=recipient.participant_id,
            summary=draft.summary,
            body=draft.body,
            protocol=draft.protocol,
            payload=payload,
            sent_at=self._now(),
        )
        candidate = state
        safe_pause = False
        if draft.protocol is TeamProtocol.PLAN_REQUEST:
            task = state.tasks[payload["task_id"]]
            if task.revision != payload["task_revision"] or task.approval_epoch != payload["approval_epoch"]:
                raise TeamValidationError("Plan request references a stale task version.")
            candidate, _record = domain.request_approval(
                state,
                actor,
                request_id=payload["request_id"],
                plan_version=payload["plan_version"],
                plan_text=draft.body,
                summary=draft.summary,
                now=self._now(),
            )
            safe_pause = True
        elif draft.protocol is TeamProtocol.PLAN_DECISION:
            decision = PlanDecision(payload["decision"])
            candidate, record = domain.decide_approval(
                state,
                actor,
                payload["request_id"],
                decision,
                feedback=payload["feedback"] or None,
                now=self._now(),
            )
            if record.task_id != payload["task_id"] or record.plan_version != payload["plan_version"]:
                raise TeamValidationError("Plan decision references a different request version.")
            candidate, _entry = domain.enqueue_member(
                candidate,
                record.member_id,
                queue_id=self._new_id(),
                reason=MemberWakeReason.APPROVAL_DECISION,
                message_ids=(message.message_id,),
                now=self._now(),
            )
        outbox = TeamOutboxEntry(self._new_id(), message, False, self._now())
        candidate = replace(candidate, outbox=(*candidate.outbox, outbox), updated_at=self._now())
        return ProtocolTransition(message, candidate, safe_pause)

    async def committed(self, transition: ProtocolTransition) -> None:
        return None

    @staticmethod
    def _validate_payload(protocol: TeamProtocol, payload: Mapping[str, object]) -> dict[str, object]:
        expected = _PAYLOAD_FIELDS[protocol]
        if set(payload) != set(expected):
            raise TeamValidationError("Protocol payload fields do not match the schema.")
        result: dict[str, object] = {}
        for field, field_type in expected.items():
            value = payload[field]
            if field_type is int:
                valid = type(value) is int and value >= 0
            else:
                valid = isinstance(value, field_type)
            if not valid:
                raise TeamValidationError(f"Protocol payload field {field} has an invalid type.")
            result[field] = value
        if len(encode_json(result)) > MAX_PROTOCOL_PAYLOAD_BYTES:
            raise TeamValidationError("Protocol payload is too large.")
        if protocol is TeamProtocol.TASK_STATUS:
            try:
                TeamTaskStatus(result["status"])
            except ValueError as exc:
                raise TeamValidationError("Task status protocol value is invalid.") from exc
        if protocol is TeamProtocol.PLAN_DECISION:
            try:
                PlanDecision(result["decision"])
            except ValueError as exc:
                raise TeamValidationError("Plan decision value is invalid.") from exc
        return result

    @staticmethod
    def _validate_direction(
        state: TeamState,
        actor: TeamActor,
        sender_is_lead: bool,
        recipient_is_lead: bool,
        recipient_id: str,
        protocol: TeamProtocol,
        payload: Mapping[str, object],
    ) -> None:
        if protocol is TeamProtocol.TEXT:
            return
        if protocol is TeamProtocol.TASK_ASSIGNMENT and not (sender_is_lead and recipient_id in state.members):
            raise TeamValidationError("Task assignments must be sent from Lead to a member.")
        if protocol is TeamProtocol.TASK_STATUS and not (actor.kind is TeamActorKind.MEMBER and recipient_is_lead):
            raise TeamValidationError("Task status must be sent from a member to Lead.")
        if protocol is TeamProtocol.PLAN_REQUEST and not (
            actor.kind is TeamActorKind.MEMBER and recipient_is_lead
        ):
            raise TeamValidationError("Plan requests must be sent from a member to Lead.")
        if protocol is TeamProtocol.PLAN_DECISION and not (
            sender_is_lead and recipient_id in state.members
        ):
            raise TeamValidationError("Plan decisions must be sent from Lead to a member.")
        if protocol is TeamProtocol.MEMBER_IDLE and not (
            actor.kind in {TeamActorKind.MEMBER, TeamActorKind.SYSTEM}
            and recipient_is_lead
            and payload["member_id"] == actor.participant_id
        ):
            raise TeamValidationError("Member idle notifications must target Lead.")
        if protocol is TeamProtocol.STOP_REQUEST and not (
            sender_is_lead
            and recipient_id in state.members
            and payload["member_id"] == recipient_id
        ):
            raise TeamValidationError("Stop requests must be sent from Lead to their target member.")

    @staticmethod
    def _registration_for_name(state: TeamState, name: str):
        try:
            return state.registry[name.casefold()]
        except KeyError as exc:
            raise TeamValidationError("Unknown message recipient.") from exc

    @staticmethod
    def _registration_for_id(state: TeamState, participant_id: str):
        for registration in state.registry.values():
            if registration.participant_id == participant_id:
                return registration
        raise TeamValidationError("Unknown message sender.")
