from __future__ import annotations

import json
from collections.abc import Sequence

from mewcode.providers import ChatMessage, MessageKind


def project_recent_turns(
    messages: Sequence[ChatMessage], count: int
) -> tuple[ChatMessage, ...]:
    if count <= 0:
        return ()
    turns = _complete_turns(messages)
    projected: list[ChatMessage] = []
    for turn in turns[-count:]:
        user = turn[0]
        projected.append(ChatMessage("user", _content_text(user.content), MessageKind.USER))
        transcript = []
        for message in turn[1:]:
            if message.kind is MessageKind.INTERNAL:
                continue
            label = {
                MessageKind.TOOL_CALL: "assistant tool call",
                MessageKind.TOOL_RESULT: "tool result",
                MessageKind.ASSISTANT: "assistant",
            }.get(message.kind, message.role)
            transcript.append(f"[{label}]\n{_content_text(message.content)}")
        projected.append(
            ChatMessage("assistant", "\n\n".join(transcript), MessageKind.ASSISTANT)
        )
    return tuple(projected)


def _complete_turns(messages: Sequence[ChatMessage]) -> list[tuple[ChatMessage, ...]]:
    turns: list[tuple[ChatMessage, ...]] = []
    current: list[ChatMessage] | None = None
    for message in messages:
        if message.kind in {
            MessageKind.SUMMARY,
            MessageKind.BOUNDARY,
            MessageKind.RESUME_NOTICE,
            MessageKind.INTERNAL,
        }:
            continue
        is_user_start = message.kind is MessageKind.USER and message.group_id is None
        if is_user_start:
            current = [message]
            continue
        if current is None:
            continue
        current.append(message)
        if message.kind is MessageKind.ASSISTANT and message.group_id is None:
            turns.append(tuple(current))
            current = None
    return turns


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
