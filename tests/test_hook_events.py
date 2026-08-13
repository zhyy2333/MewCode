from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from mewcode.hooks import HookEvent, is_allowed_field, make_event


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
