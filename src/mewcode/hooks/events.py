from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from mewcode.matching import MatchSubjectKind

from .models import (
    DEFAULT_HOOK_LIMITS,
    HookEvent,
    HookEventContext,
    HookLimits,
    SerializedHookEnvelope,
)


COMMON_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "occurred_at",
        "workspace.root",
        "session.id",
        "session.resumed",
    }
)
TURN_SCOPE_FIELDS = frozenset({"turn.id", "turn.mode"})
TASK_SCOPE_FIELDS = frozenset(
    {"task.id", "task.parent_run_id", "task.component"}
)

EVENT_FIELDS: Mapping[HookEvent, frozenset[str]] = MappingProxyType(
    {
        HookEvent.SESSION_START: COMMON_EVENT_FIELDS | TASK_SCOPE_FIELDS,
        HookEvent.SESSION_END: COMMON_EVENT_FIELDS | TASK_SCOPE_FIELDS | {"session.status"},
        HookEvent.TURN_START: COMMON_EVENT_FIELDS | TASK_SCOPE_FIELDS
        | {"turn.id", "turn.mode", "turn.input_summary"},
        HookEvent.TURN_END: COMMON_EVENT_FIELDS | TASK_SCOPE_FIELDS
        | {"turn.id", "turn.mode", "turn.input_summary", "turn.status"},
        HookEvent.MESSAGE_BEFORE: COMMON_EVENT_FIELDS | TURN_SCOPE_FIELDS | TASK_SCOPE_FIELDS
        | {
            "message.id",
            "message.component",
            "message.profile",
            "message.run_id",
            "message.iteration",
            "message.message_count",
            "message.tool_count",
            "message.max_output_tokens",
        },
        HookEvent.MESSAGE_AFTER: COMMON_EVENT_FIELDS | TURN_SCOPE_FIELDS | TASK_SCOPE_FIELDS
        | {
            "message.id",
            "message.component",
            "message.profile",
            "message.run_id",
            "message.iteration",
            "message.message_count",
            "message.tool_count",
            "message.max_output_tokens",
            "message.status",
            "message.finish_reason",
            "message.response_summary",
            "message.error",
        },
        HookEvent.TOOL_BEFORE: COMMON_EVENT_FIELDS | TURN_SCOPE_FIELDS | TASK_SCOPE_FIELDS
        | {
            "tool.call_id",
            "tool.name",
            "tool.arguments",
            "tool.target.kind",
            "tool.target.value",
        },
        HookEvent.TOOL_AFTER: COMMON_EVENT_FIELDS | TURN_SCOPE_FIELDS | TASK_SCOPE_FIELDS
        | {
            "tool.call_id",
            "tool.name",
            "tool.arguments",
            "tool.target.kind",
            "tool.target.value",
            "tool.status",
            "tool.ok",
            "tool.result_summary",
            "tool.error",
        },
        HookEvent.COMPACT_BEFORE: COMMON_EVENT_FIELDS | TURN_SCOPE_FIELDS | TASK_SCOPE_FIELDS
        | {
            "compaction.mode",
            "compaction.message_count_before",
        },
        HookEvent.COMPACT_AFTER: COMMON_EVENT_FIELDS | TURN_SCOPE_FIELDS | TASK_SCOPE_FIELDS
        | {
            "compaction.mode",
            "compaction.status",
            "compaction.changed",
            "compaction.message_count_before",
            "compaction.message_count_after",
            "compaction.error",
        },
        HookEvent.SYSTEM_ERROR: COMMON_EVENT_FIELDS | TASK_SCOPE_FIELDS
        | {
            "error.id",
            "error.component",
            "error.kind",
            "error.message",
        },
    }
)


def is_allowed_field(event: HookEvent, field: str) -> bool:
    if field in EVENT_FIELDS[event]:
        return True
    return (
        event in {HookEvent.TOOL_BEFORE, HookEvent.TOOL_AFTER}
        and field.startswith("tool.arguments.")
        and len(field) > len("tool.arguments.")
    )


def make_event(
    event: HookEvent,
    *,
    workspace: Path | str,
    session_id: str,
    resumed: bool,
    values: Mapping[str, object] | None = None,
    occurred_at: datetime | None = None,
    match_kinds: Mapping[str, MatchSubjectKind] | None = None,
) -> HookEventContext:
    timestamp = occurred_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Hook event timestamps must be timezone-aware.")
    tree: dict[str, object] = {
        "schema_version": 1,
        "event": event.value,
        "occurred_at": timestamp.astimezone(timezone.utc).isoformat(),
        "workspace": MappingProxyType({"root": str(Path(workspace).resolve())}),
        "session": MappingProxyType({"id": session_id, "resumed": resumed}),
    }
    if values:
        tree.update({key: _freeze(value) for key, value in values.items()})
    return HookEventContext(
        event=event,
        occurred_at=timestamp,
        values=MappingProxyType(tree),
        match_kinds=MappingProxyType(dict(match_kinds or {})),
    )


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def serialize_event(
    event: HookEventContext,
    limits: HookLimits = DEFAULT_HOOK_LIMITS,
) -> SerializedHookEnvelope:
    truncated: list[str] = []

    def convert(value: object, path: str, depth: int) -> object:
        if depth > 16:
            truncated.append(path)
            return "[truncated:depth]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) <= 64 * 1024:
                return value
            truncated.append(path)
            return encoded[: 64 * 1024].decode("utf-8", errors="ignore") + "…[truncated]"
        if isinstance(value, Mapping):
            result: dict[str, object] = {}
            for position, (key, child) in enumerate(value.items()):
                child_path = f"{path}.{key}" if path else str(key)
                if position >= 256:
                    truncated.append(path or "$")
                    break
                result[str(key)] = convert(child, child_path, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            result = []
            for position, child in enumerate(value):
                if position >= 256:
                    truncated.append(path or "$")
                    break
                result.append(convert(child, f"{path}.{position}", depth + 1))
            return result
        truncated.append(path)
        return f"[unsupported:{type(value).__name__}]"

    value = convert(event.values, "", 0)
    assert isinstance(value, dict)

    def encode() -> bytes:
        value["truncated_fields"] = sorted(set(item for item in truncated if item))
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    encoded = encode()
    if len(encoded) > limits.envelope_bytes:
        # Tool arguments are the only intentionally large internal branch. Preserve
        # its presence while replacing its external copy deterministically.
        tool = value.get("tool")
        if isinstance(tool, dict) and "arguments" in tool:
            tool["arguments"] = "[truncated:envelope_budget]"
            truncated.append("tool.arguments")
            encoded = encode()
    if len(encoded) > limits.envelope_bytes:
        # Fall back to a bounded metadata envelope instead of emitting invalid JSON.
        value = {
            "schema_version": event.values.get("schema_version", 1),
            "event": event.event.value,
            "occurred_at": event.values.get("occurred_at"),
            "truncated_fields": ["$"],
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        truncated = ["$"]
    return SerializedHookEnvelope(
        value=MappingProxyType(value),
        encoded=encoded,
        truncated_fields=tuple(sorted(set(truncated))),
    )
