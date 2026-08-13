from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from mewcode.hooks import HookEvent, HookLimits, is_allowed_field, make_event, serialize_event


def test_registry_has_exactly_eleven_events() -> None:
    assert len(HookEvent) == 11
    assert is_allowed_field(HookEvent.TOOL_BEFORE, "tool.arguments.command.options.0")
    assert not is_allowed_field(HookEvent.TURN_START, "tool.arguments.command")


def test_base_event_is_read_only_and_normalized(tmp_path: Path) -> None:
    event = make_event(
        HookEvent.SESSION_START,
        workspace=tmp_path,
        session_id="s1",
        resumed=False,
    )
    assert event.values["event"] == "session.start"
    assert event.values["workspace"]["root"] == str(tmp_path.resolve())
    with pytest.raises(TypeError):
        event.values["event"] = "changed"  # type: ignore[index]


def test_external_envelope_is_bounded_and_marks_tool_arguments(tmp_path: Path) -> None:
    event = make_event(
        HookEvent.TOOL_BEFORE,
        workspace=tmp_path,
        session_id="s",
        resumed=False,
        values={"tool": {"name": "x", "arguments": {"value": "z" * 20_000}}},
    )
    envelope = serialize_event(event, HookLimits(envelope_bytes=1024))
    assert len(envelope.encoded) <= 1024
    assert "tool.arguments" in envelope.truncated_fields
    assert event.values["tool"]["arguments"]["value"] == "z" * 20_000
