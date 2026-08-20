from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
import dataclasses
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any

from mewcode.agent import AgentControlContext, AgentMode
from mewcode.tools import PermissionTargetKind, ToolPermissionSpec, ToolResult, ToolSafety

from .coordinator import TeamCoordinator
from .models import (
    PlanDecision,
    TeamActor,
    TeamMemberRuntimeView,
    TeamProtocol,
    TeamTaskStatus,
    TeamValidationError,
)


TEAM_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "name": {"type": "string"},
        "leader_name": {"type": "string"},
        "workspace": {"type": "string"},
    },
    "required": ["action"],
}
TEAM_MEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "member_id": {"type": "string"},
        "name": {"type": "string"},
        "role": {"type": "string"},
        "backend": {"type": "string"},
        "requires_approval": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["action"],
}
TEAM_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "task_id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "dependency_ids": {"type": "array", "items": {"type": "string"}},
        "member": {"type": "string"},
        "status": {"type": "string"},
        "assignee": {"type": "string"},
        "expected_revision": {"type": "integer"},
        "result": {"type": "string"},
    },
    "required": ["action"],
}
TEAM_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "recipient": {"type": "string"},
        "summary": {"type": "string"},
        "body": {"type": "string"},
        "protocol": {"type": "string"},
        "payload": {"type": "object"},
        "message_ids": {"type": "array", "items": {"type": "string"}},
        "unread_only": {"type": "boolean"},
        "limit": {"type": "integer"},
        "cursor": {"type": "string"},
        "task_id": {"type": "string"},
        "plan_version": {"type": "integer"},
        "plan_text": {"type": "string"},
        "request_id": {"type": "string"},
        "decision": {"type": "string"},
        "feedback": {"type": "string"},
    },
    "required": ["action"],
}


class _Operation:
    def __init__(self, invoke: Callable[[], Awaitable[ToolResult]]) -> None:
        self._invoke = invoke
        self._result: ToolResult | None = None
        self._cancelled = False

    async def events(self) -> AsyncIterator[object]:
        if not self._cancelled:
            self._result = await self._invoke()
        if False:
            yield object()

    @property
    def result(self) -> ToolResult:
        if self._result is None:
            return ToolResult(False, "team", "", "Team operation did not complete.")
        return self._result

    async def cancel(self) -> None:
        self._cancelled = True


class _BaseTeamTool:
    description = "Persistent team collaboration operations."
    safety = ToolSafety.READ_ONLY
    permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL, "team")

    def control_operation(
        self,
        arguments: dict[str, object],
        context: AgentControlContext | None,
    ) -> _Operation:
        return _Operation(lambda: self._safe_invoke(arguments, context))

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return await self._safe_invoke(arguments, None)

    async def _safe_invoke(
        self,
        arguments: dict[str, object],
        context: AgentControlContext | None,
    ) -> ToolResult:
        try:
            value, metadata = await self._invoke(arguments, context)
            return ToolResult(True, self.name, _encode(value), metadata=metadata)
        except Exception as exc:
            return ToolResult(
                False,
                self.name,
                "",
                " ".join(str(exc).splitlines())[:512] or type(exc).__name__,
            )

    async def _invoke(self, arguments, context):
        raise NotImplementedError


class TeamLifecycleTool(_BaseTeamTool):
    name = "team"
    parameters_schema = TEAM_SCHEMA

    def __init__(
        self,
        coordinator: TeamCoordinator,
        *,
        root_session_id: Callable[[], str],
    ) -> None:
        self._coordinator = coordinator
        self._root_session_id = root_session_id

    async def _invoke(self, arguments, context):
        action = _action(arguments, {"create", "list", "attach", "relink", "detach"})
        _require_root_context(context)
        if context.mode is AgentMode.PLAN and action != "list":
            raise TeamValidationError("PLAN mode only permits listing teams.")
        allowed = {
            "create": ({"action", "name", "leader_name"}, {"name"}),
            "list": ({"action"}, set()),
            "attach": ({"action", "name"}, {"name"}),
            "relink": ({"action", "workspace"}, {"workspace"}),
            "detach": ({"action"}, set()),
        }[action]
        _fields(arguments, *allowed)
        if action == "create":
            value = await self._coordinator.create(
                _string(arguments, "name"),
                root_session_id=self._root_session_id(),
                leader_name=str(arguments.get("leader_name", "lead")),
            )
        elif action == "list":
            value = self._coordinator.list()
        elif action == "attach":
            value = await self._coordinator.attach(
                _string(arguments, "name"), root_session_id=self._root_session_id()
            )
        elif action == "relink":
            value = await self._coordinator.relink(Path(_string(arguments, "workspace")))
        else:
            await self._coordinator.detach()
            value = {"detached": True}
        return value, {}


class TeamMemberTool(_BaseTeamTool):
    name = "team_member"
    parameters_schema = TEAM_MEMBER_SCHEMA

    def __init__(self, coordinator: TeamCoordinator) -> None:
        self._coordinator = coordinator

    async def _invoke(self, arguments, context):
        action = _action(arguments, {"list", "add", "refresh_role", "resume", "stop", "remove"})
        _require_root_context(context)
        if context.mode is AgentMode.PLAN and action != "list":
            raise TeamValidationError("PLAN mode only permits listing team members.")
        services = self._coordinator.services
        if services is None or services.roster is None:
            raise TeamValidationError("No valid team roster is attached.")
        actor = self._coordinator.lead_actor()
        specs = {
            "list": ({"action"}, set()),
            "add": ({"action", "name", "role", "backend", "requires_approval"}, {"name", "role", "requires_approval"}),
            "refresh_role": ({"action", "member_id", "role"}, {"member_id", "role"}),
            "resume": ({"action", "member_id", "reason"}, {"member_id", "reason"}),
            "stop": ({"action", "member_id", "reason"}, {"member_id", "reason"}),
            "remove": ({"action", "member_id"}, {"member_id"}),
        }
        _fields(arguments, *specs[action])
        if action == "list":
            value = services.roster.list_members(actor)
        elif action == "add":
            value = await services.roster.add_member(
                actor,
                name=_string(arguments, "name"),
                role_name=_string(arguments, "role"),
                backend=str(arguments.get("backend", "auto")),
                requires_approval=_boolean(arguments, "requires_approval"),
            )
        elif action == "refresh_role":
            value = await services.roster.refresh_role(
                actor, _string(arguments, "member_id"), role_name=_string(arguments, "role")
            )
        elif action == "resume":
            value = await services.roster.resume(
                actor, _string(arguments, "member_id"), reason=_string(arguments, "reason")
            )
        elif action == "stop":
            value = await services.roster.stop(
                actor, _string(arguments, "member_id"), reason=_string(arguments, "reason")
            )
        else:
            value = await services.roster.remove_member(actor, _string(arguments, "member_id"))
        return value, {}


class TeamTaskTool(_BaseTeamTool):
    name = "team_task"
    parameters_schema = TEAM_TASK_SCHEMA

    def __init__(
        self,
        service: Callable[[], Any],
        actor: Callable[[], TeamActor],
        permit: Callable[[], Any] | None = None,
    ) -> None:
        self._service = service
        self._actor = actor
        self._permit = permit

    async def _invoke(self, arguments, context):
        action = _action(arguments, {"create", "get", "list", "update", "assign", "claim", "transition", "delete"})
        if context is not None and context.mode is AgentMode.PLAN and action not in {"get", "list"}:
            raise TeamValidationError("PLAN mode only permits reading team tasks.")
        specs = {
            "create": ({"action", "title", "description", "dependency_ids"}, {"title", "description"}),
            "get": ({"action", "task_id"}, {"task_id"}),
            "list": ({"action", "status", "assignee"}, set()),
            "update": ({"action", "task_id", "expected_revision", "title", "description", "dependency_ids"}, {"task_id", "expected_revision"}),
            "assign": ({"action", "task_id", "member", "expected_revision"}, {"task_id", "member", "expected_revision"}),
            "claim": ({"action", "task_id", "expected_revision"}, {"task_id", "expected_revision"}),
            "transition": ({"action", "task_id", "status", "expected_revision", "result"}, {"task_id", "status", "expected_revision"}),
            "delete": ({"action", "task_id", "expected_revision"}, {"task_id", "expected_revision"}),
        }
        _fields(arguments, *specs[action])
        service, actor = self._service(), self._actor()
        task_id = str(arguments.get("task_id", ""))
        async def dispatch():
            if action == "create":
                return await service.create(actor, title=_string(arguments, "title"), description=_string(arguments, "description"), dependency_ids=_strings(arguments.get("dependency_ids", ())))
            if action == "get":
                return service.get(actor, task_id)
            if action == "list":
                status = TeamTaskStatus(arguments["status"]) if "status" in arguments else None
                return service.list(actor, status=status, assignee=arguments.get("assignee"))
            if action == "update":
                return await service.update(actor, task_id, expected_revision=_integer(arguments, "expected_revision"), title=arguments.get("title"), description=arguments.get("description"), dependency_ids=_strings(arguments["dependency_ids"]) if "dependency_ids" in arguments else None)
            if action == "assign":
                return await service.assign(actor, task_id, _string(arguments, "member"), expected_revision=_integer(arguments, "expected_revision"))
            if action == "claim":
                return await service.claim(actor, task_id, expected_revision=_integer(arguments, "expected_revision"))
            if action == "transition":
                return await service.transition(actor, task_id, TeamTaskStatus(_string(arguments, "status")), expected_revision=_integer(arguments, "expected_revision"), result=str(arguments.get("result", "")))
            await service.delete(actor, task_id, expected_revision=_integer(arguments, "expected_revision"))
            return {"deleted": True, "task_id": task_id}

        value = await _guarded_action(
            self._permit,
            action not in {"get", "list"},
            dispatch,
        )
        return value, {}


class TeamMessageTool(_BaseTeamTool):
    name = "team_message"
    parameters_schema = TEAM_MESSAGE_SCHEMA

    def __init__(self, mailbox: Callable[[], Any], approvals: Callable[[], Any], actor: Callable[[], TeamActor], permit: Callable[[], Any] | None = None) -> None:
        self._mailbox = mailbox
        self._approvals = approvals
        self._actor = actor
        self._permit = permit

    async def _invoke(self, arguments, context):
        action = _action(arguments, {"send", "broadcast", "list", "mark_read", "plan_request", "plan_decision"})
        if context is not None and context.mode is AgentMode.PLAN and action != "list":
            raise TeamValidationError("PLAN mode only permits reading team messages.")
        specs = {
            "send": ({"action", "recipient", "summary", "body", "protocol", "payload"}, {"recipient", "summary", "body", "protocol"}),
            "broadcast": ({"action", "summary", "body", "protocol", "payload"}, {"summary", "body", "protocol"}),
            "list": ({"action", "unread_only", "limit", "cursor"}, set()),
            "mark_read": ({"action", "message_ids"}, {"message_ids"}),
            "plan_request": ({"action", "task_id", "plan_version", "plan_text", "summary"}, {"task_id", "plan_version", "plan_text", "summary"}),
            "plan_decision": ({"action", "request_id", "decision", "feedback"}, {"request_id", "decision"}),
        }
        _fields(arguments, *specs[action])
        mailbox, approvals, actor = self._mailbox(), self._approvals(), self._actor()
        metadata: dict[str, object] = {}
        payload = arguments.get("payload", {})
        if not isinstance(payload, Mapping):
            raise TeamValidationError("payload must be an object")
        async def dispatch():
            if action == "send":
                sent = await mailbox.send(actor, recipient=_string(arguments, "recipient"), summary=_string(arguments, "summary"), body=_string(arguments, "body"), protocol=TeamProtocol(_string(arguments, "protocol")), payload=payload)
                if sent.safe_pause:
                    metadata["safe_pause"] = "awaiting_approval"
                if sent.wake is not None:
                    metadata["wake"] = sent.wake.status.value
                return sent
            if action == "broadcast":
                return await mailbox.broadcast(actor, summary=_string(arguments, "summary"), body=_string(arguments, "body"), protocol=TeamProtocol(_string(arguments, "protocol")), payload=payload)
            if action == "list":
                return mailbox.list(actor, unread_only=bool(arguments.get("unread_only", True)), limit=int(arguments.get("limit", 100)), cursor=arguments.get("cursor"))
            if action == "mark_read":
                return await mailbox.mark_read(actor, _strings(arguments["message_ids"]))
            if action == "plan_request":
                requested = await approvals.request(actor, task_id=_string(arguments, "task_id"), plan_version=_integer(arguments, "plan_version"), plan_text=_string(arguments, "plan_text"), summary=_string(arguments, "summary"))
                metadata["safe_pause"] = "awaiting_approval"
                return requested
            return await approvals.decide(actor, request_id=_string(arguments, "request_id"), decision=PlanDecision(_string(arguments, "decision")), feedback=arguments.get("feedback"))

        value = await _guarded_action(
            self._permit,
            action in {"send", "broadcast"},
            dispatch,
        )
        return value, metadata


async def _guarded_action(
    permit_factory: Callable[[], Any] | None,
    guarded: bool,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    if not guarded or permit_factory is None:
        return await operation()
    async with permit_factory():
        return await operation()


def _action(arguments: Mapping[str, object], allowed: set[str]) -> str:
    value = arguments.get("action")
    if not isinstance(value, str) or value not in allowed:
        raise TeamValidationError("Unknown or missing team tool action.")
    return value


def _fields(arguments: Mapping[str, object], allowed: set[str], required: set[str]) -> None:
    unknown = set(arguments).difference(allowed)
    missing = required.difference(arguments)
    if unknown:
        raise TeamValidationError("Unknown argument: " + ", ".join(sorted(unknown)))
    if missing:
        raise TeamValidationError("Missing argument: " + ", ".join(sorted(missing)))


def _require_root_context(context: AgentControlContext | None) -> None:
    if context is None:
        raise TeamValidationError("Root team operation requires Agent control context.")


def _string(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TeamValidationError(f"{name} must be a non-empty string")
    return value


def _integer(arguments: Mapping[str, object], name: str) -> int:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TeamValidationError(f"{name} must be an integer")
    return value


def _boolean(arguments: Mapping[str, object], name: str) -> bool:
    value = arguments.get(name)
    if not isinstance(value, bool):
        raise TeamValidationError(f"{name} must be a boolean")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise TeamValidationError("Expected an array of strings")
    return tuple(value)


def _encode(value: object) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonable(value: object) -> object:
    if isinstance(value, TeamMemberRuntimeView):
        member = value.member
        return {
            "member_id": member.member_id,
            "name": member.name.value,
            "role": member.role.role_name,
            "backend": member.backend.value,
            "status": member.status.value,
            "requires_approval": member.requires_approval,
            "current_task_id": member.current_task_id,
            "pane_health": value.pane_health.value,
            "diagnostic": value.diagnostic,
        }
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
