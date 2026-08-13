from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from mewcode.matching import MatchSubjectKind

from .models import HookEvent, HookEventContext


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

EVENT_FIELDS: Mapping[HookEvent, frozenset[str]] = MappingProxyType(
    {
        HookEvent.SESSION_START: COMMON_EVENT_FIELDS,
        HookEvent.SESSION_END: COMMON_EVENT_FIELDS | {"session.status"},
        HookEvent.TURN_START: COMMON_EVENT_FIELDS
        | {"turn.id", "turn.mode", "turn.input_summary"},
        HookEvent.TURN_END: COMMON_EVENT_FIELDS
        | {"turn.id", "turn.mode", "turn.input_summary", "turn.status"},
        HookEvent.MESSAGE_BEFORE: COMMON_EVENT_FIELDS
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
        HookEvent.MESSAGE_AFTER: COMMON_EVENT_FIELDS
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
        HookEvent.TOOL_BEFORE: COMMON_EVENT_FIELDS
        | {
            "tool.call_id",
            "tool.name",
            "tool.arguments",
            "tool.target.kind",
            "tool.target.value",
        },
        HookEvent.TOOL_AFTER: COMMON_EVENT_FIELDS
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
        HookEvent.COMPACT_BEFORE: COMMON_EVENT_FIELDS
        | {
            "compaction.mode",
            "compaction.message_count_before",
        },
        HookEvent.COMPACT_AFTER: COMMON_EVENT_FIELDS
        | {
            "compaction.mode",
            "compaction.status",
            "compaction.changed",
            "compaction.message_count_before",
            "compaction.message_count_after",
            "compaction.error",
        },
        HookEvent.SYSTEM_ERROR: COMMON_EVENT_FIELDS
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
        tree.update(values)
    return HookEventContext(
        event=event,
        occurred_at=timestamp,
        values=MappingProxyType(tree),
        match_kinds=MappingProxyType(dict(match_kinds or {})),
    )
