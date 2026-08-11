from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from mewcode.continuity.session_codec import (
    decode_message,
    encode_history,
    encode_message,
    encode_plan,
    encode_start,
    replay_file,
    session_title,
    valid_tool_prefix,
)
from mewcode.continuity.session_models import StoredPlan
from mewcode.providers import ChatMessage, MessageKind

NOW = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)


def test_models_and_message_roundtrip() -> None:
    messages = (
        ChatMessage("user", "hello"),
        ChatMessage("assistant", {"type": "function_call", "call_id": "1", "name": "x", "arguments": "{}"}, MessageKind.TOOL_CALL, "g"),
    )
    assert tuple(decode_message(encode_message(item)) for item in messages) == messages
    with pytest.raises(ValueError):
        encode_message(ChatMessage("assistant", object()))


def test_record_encoding_is_one_line() -> None:
    records = (
        encode_start("20260811-120000-abcd", NOW),
        encode_history((ChatMessage("user", "hi"),), "append", NOW),
        encode_plan(StoredPlan("task", "plan"), NOW),
    )
    assert all(item.endswith(b"\n") and item.count(b"\n") == 1 for item in records)


def test_replay_append_replace_and_plan(tmp_path: Path) -> None:
    session_id = "20260811-120000-abcd"
    path = tmp_path / f"{session_id}.jsonl"
    path.write_bytes(
        encode_start(session_id, NOW)
        + encode_history((ChatMessage("user", "old"),), "append", NOW)
        + encode_history((ChatMessage("user", "new"),), "replace", NOW)
        + encode_plan(StoredPlan("task", "plan"), NOW)
    )
    replay = replay_file(path, session_id)
    assert replay.messages == (ChatMessage("user", "new"),)
    assert replay.pending_plan == StoredPlan("task", "plan")
    assert replay.recoverable


def test_malformed_and_partial_lines_are_reported(tmp_path: Path) -> None:
    session_id = "20260811-120000-abcd"
    path = tmp_path / f"{session_id}.jsonl"
    valid = encode_start(session_id, NOW)
    bad = b"{bad json}\n"
    path.write_bytes(valid + bad + encode_history((ChatMessage("user", "ok"),), "append", NOW) + b'{"partial"')
    replay = replay_file(path, session_id)
    assert replay.messages == (ChatMessage("user", "ok"),)
    assert replay.invalid_lines == 2
    assert replay.partial_offset == len(valid + bad + encode_history((ChatMessage("user", "ok"),), "append", NOW))


def test_unknown_version_is_skipped(tmp_path: Path) -> None:
    session_id = "20260811-120000-abcd"
    path = tmp_path / f"{session_id}.jsonl"
    unknown = (json.dumps({"version": 99, "type": "x", "at": NOW.isoformat()}) + "\n").encode()
    path.write_bytes(encode_start(session_id, NOW) + unknown)
    assert replay_file(path, session_id).invalid_lines == 1


def test_openai_pair_and_invalid_result() -> None:
    call = ChatMessage("assistant", {"type": "function_call", "call_id": "1", "name": "x", "arguments": "{}"}, MessageKind.TOOL_CALL, "g")
    result = ChatMessage("tool", {"type": "function_call_output", "call_id": "1", "output": "ok"}, MessageKind.TOOL_RESULT, "g")
    assert valid_tool_prefix((call, result)) == 2
    orphan = ChatMessage("tool", {"type": "function_call_output", "call_id": "2", "output": "bad"}, MessageKind.TOOL_RESULT, "g")
    assert valid_tool_prefix((call, orphan)) == 0


def test_anthropic_multi_pair() -> None:
    call = ChatMessage(
        "assistant",
        [{"type": "tool_use", "id": "1"}, {"type": "tool_use", "id": "2"}],
        MessageKind.TOOL_CALL,
        "g",
    )
    result = ChatMessage(
        "user",
        [{"type": "tool_result", "tool_use_id": "1"}, {"type": "tool_result", "tool_use_id": "2"}],
        MessageKind.TOOL_RESULT,
        "g",
    )
    assert valid_tool_prefix((call, result)) == 2
    assert valid_tool_prefix((call,)) == 0


def test_summary_title_is_deterministic() -> None:
    messages = (ChatMessage("assistant", "x"), ChatMessage("user", "  hello   world " + "x" * 80))
    title = session_title(messages, "fallback")
    assert title.startswith("hello world")
    assert len(title) == 60
