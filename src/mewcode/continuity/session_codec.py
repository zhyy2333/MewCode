from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from mewcode.providers import ChatMessage, MessageKind

from .session_models import SessionReplay, SessionScan, StoredPlan, StoredSkillActivation
from .sanitization import sanitize_text

SESSION_VERSION = 1


def encode_start(session_id: str, at: datetime) -> bytes:
    return _encode({"version": SESSION_VERSION, "type": "start", "at": _time(at), "session_id": session_id})


def encode_history(
    messages: Sequence[ChatMessage],
    operation: str,
    at: datetime,
) -> bytes:
    if operation not in {"append", "replace"}:
        raise ValueError("invalid history operation")
    return _encode(
        {
            "version": SESSION_VERSION,
            "type": "history",
            "at": _time(at),
            "operation": operation,
            "messages": [encode_message(message) for message in messages],
        }
    )


def encode_plan(plan: StoredPlan | None, at: datetime) -> bytes:
    payload = None if plan is None else {"task": plan.task, "text": plan.text}
    return _encode(
        {
            "version": SESSION_VERSION,
            "type": "plan_state",
            "at": _time(at),
            "pending_plan": payload,
        }
    )


def encode_skills(skills: Sequence[StoredSkillActivation], at: datetime) -> bytes:
    return _encode(
        {
            "version": SESSION_VERSION,
            "type": "skill_state",
            "at": _time(at),
            "active_skills": [
                {"name": item.name, "input": item.input} for item in skills
            ],
        }
    )


def encode_message(message: ChatMessage) -> dict[str, Any]:
    _validate_json(message.content)
    return {
        "role": message.role,
        "kind": message.kind.value if message.kind is not None else None,
        "group_id": message.group_id,
        "content": message.content,
    }


def decode_message(payload: Any) -> ChatMessage:
    if not isinstance(payload, dict) or set(payload) != {"role", "kind", "group_id", "content"}:
        raise ValueError("invalid message shape")
    role = payload["role"]
    kind_value = payload["kind"]
    group_id = payload["group_id"]
    if not isinstance(role, str) or not role:
        raise ValueError("invalid message role")
    try:
        kind = MessageKind(kind_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid message kind") from exc
    if group_id is not None and not isinstance(group_id, str):
        raise ValueError("invalid group id")
    _validate_json(payload["content"])
    return ChatMessage(role, payload["content"], kind, group_id)


def replay_file(path: Path, session_id: str) -> SessionReplay:
    messages: list[ChatMessage] = []
    pending: StoredPlan | None = None
    active_skills: tuple[StoredSkillActivation, ...] = ()
    created_at: datetime | None = None
    last_activity: datetime | None = None
    invalid = 0
    partial_offset: int | None = None
    valid_start = False
    offset = 0
    with path.open("rb") as handle:
        while True:
            raw = handle.readline()
            if not raw:
                break
            start_offset = offset
            offset += len(raw)
            if not raw.endswith(b"\n"):
                partial_offset = start_offset
                invalid += 1
                break
            try:
                record = json.loads(raw.decode("utf-8"))
                if not isinstance(record, dict) or record.get("version") != SESSION_VERSION:
                    raise ValueError("invalid record")
                at = _parse_time(record.get("at"))
                record_type = record.get("type")
                if record_type == "start":
                    if record.get("session_id") != session_id:
                        raise ValueError("session id mismatch")
                    valid_start = True
                    created_at = created_at or at
                elif record_type == "history":
                    operation = record.get("operation")
                    decoded = tuple(decode_message(item) for item in _require_list(record.get("messages")))
                    if operation == "append":
                        messages.extend(decoded)
                    elif operation == "replace":
                        messages = list(decoded)
                    else:
                        raise ValueError("invalid history operation")
                elif record_type == "plan_state":
                    pending = _decode_plan(record.get("pending_plan"))
                elif record_type == "skill_state":
                    active_skills = _decode_skills(record.get("active_skills"))
                else:
                    raise ValueError("unknown record")
                last_activity = at if last_activity is None or at > last_activity else last_activity
            except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                invalid += 1
    return SessionReplay(
        session_id,
        tuple(messages),
        pending,
        active_skills,
        created_at,
        last_activity,
        invalid,
        partial_offset,
        valid_start,
    )


def scan_file(path: Path, session_id: str) -> SessionScan:
    title = session_id
    message_count = 0
    last_activity: datetime | None = None
    invalid = 0
    valid_start = False
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                invalid += 1
                break
            try:
                record = json.loads(raw.decode("utf-8"))
                if not isinstance(record, dict) or record.get("version") != SESSION_VERSION:
                    raise ValueError("invalid record")
                at = _parse_time(record.get("at"))
                record_type = record.get("type")
                if record_type == "start":
                    if record.get("session_id") != session_id:
                        raise ValueError("session id mismatch")
                    valid_start = True
                elif record_type == "history":
                    decoded = tuple(
                        decode_message(item)
                        for item in _require_list(record.get("messages"))
                    )
                    operation = record.get("operation")
                    if operation == "replace":
                        message_count = len(decoded)
                        title = session_title(decoded, session_id)
                    elif operation == "append":
                        if title == session_id:
                            title = session_title(decoded, session_id)
                        message_count += len(decoded)
                    else:
                        raise ValueError("invalid history operation")
                elif record_type == "plan_state":
                    _decode_plan(record.get("pending_plan"))
                elif record_type == "skill_state":
                    _decode_skills(record.get("active_skills"))
                else:
                    raise ValueError("unknown record")
                last_activity = at if last_activity is None or at > last_activity else last_activity
            except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                invalid += 1
    return SessionScan(
        session_id,
        title,
        message_count,
        last_activity,
        invalid,
        valid_start,
    )


def valid_tool_prefix(messages: Sequence[ChatMessage]) -> int:
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.group_id is None:
            if message.kind in {MessageKind.TOOL_CALL, MessageKind.TOOL_RESULT}:
                return index
            index += 1
            continue
        group_start = index
        group_id = message.group_id
        group: list[ChatMessage] = []
        while index < len(messages) and messages[index].group_id == group_id:
            group.append(messages[index])
            index += 1
        tool_related = any(
            item.kind in {MessageKind.TOOL_CALL, MessageKind.TOOL_RESULT}
            for item in group
        )
        if not tool_related:
            continue
        calls: list[str] = []
        results: list[str] = []
        saw_result = False
        valid = True
        for item in group:
            if item.kind is MessageKind.TOOL_CALL:
                if saw_result:
                    valid = False
                calls.extend(_tool_ids(item, result=False))
            elif item.kind is MessageKind.TOOL_RESULT:
                saw_result = True
                results.extend(_tool_ids(item, result=True))
        if (
            not valid
            or not calls
            or len(calls) != len(set(calls))
            or len(results) != len(set(results))
            or set(calls) != set(results)
        ):
            return group_start
    return len(messages)


def session_title(messages: Sequence[ChatMessage], fallback: str) -> str:
    for message in messages:
        if message.kind is not MessageKind.USER or not isinstance(message.content, str):
            continue
        text = " ".join(sanitize_text(message.content).split())
        if text:
            return text[:60]
    return fallback


def _tool_ids(message: ChatMessage, *, result: bool) -> list[str]:
    content = message.content
    if isinstance(content, dict):
        expected = "function_call_output" if result else "function_call"
        if content.get("type") != expected:
            return []
        key = "call_id"
        value = content.get(key)
        return [value] if isinstance(value, str) and value else []
    if isinstance(content, list):
        expected = "tool_result" if result else "tool_use"
        key = "tool_use_id" if result else "id"
        values = [
            item.get(key)
            for item in content
            if isinstance(item, dict) and item.get("type") == expected
        ]
        return [value for value in values if isinstance(value, str) and value]
    return []


def _decode_plan(payload: Any) -> StoredPlan | None:
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {"task", "text"}:
        raise ValueError("invalid plan")
    task, text = payload["task"], payload["text"]
    if not isinstance(task, str) or not task.strip() or not isinstance(text, str) or not text.strip():
        raise ValueError("invalid plan")
    return StoredPlan(task, text)


def _decode_skills(payload: Any) -> tuple[StoredSkillActivation, ...]:
    values = _require_list(payload)
    result: list[StoredSkillActivation] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict) or set(item) != {"name", "input"}:
            raise ValueError("invalid Skill activation")
        name, input_text = item["name"], item["input"]
        if not isinstance(name, str) or not name or not isinstance(input_text, str):
            raise ValueError("invalid Skill activation")
        if name in seen:
            raise ValueError("duplicate Skill activation")
        seen.add(name)
        result.append(StoredSkillActivation(name, input_text))
    return tuple(result)


def _require_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("expected list")
    return value


def _validate_json(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("message content must be JSON-compatible") from exc
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if not all(isinstance(key, str) for key in current):
                raise ValueError("message content keys must be strings")
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


def _encode(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session timestamps must be timezone-aware")
    return value.isoformat()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid timestamp")
    return parsed
