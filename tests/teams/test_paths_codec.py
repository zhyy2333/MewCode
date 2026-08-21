from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dataclasses import replace
import json

from mewcode.teams.models import (
    PANE_BINDING_SCHEMA_VERSION,
    TeamCorruptionError,
    TeamMemberBackend,
    TeamValidationError,
    TerminalPaneBinding,
)
from mewcode.teams.codec import (
    decode_coordinator_settings,
    decode_json,
    decode_team_state,
    decode_terminal_pane_binding,
    encode_coordinator_settings,
    encode_team_state,
    encode_terminal_pane_binding,
)
from mewcode.teams.coordinator_models import (
    COORDINATOR_POLICY_VERSION,
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorSettings,
)
from mewcode.teams.paths import TeamNamePolicy, TeamPaths

from .helpers import FakeClock, empty_state, state_with_members


@pytest.mark.parametrize("value", ["alpha", "Alpha-2", "a.b_c"])
def test_name_policy_accepts_safe_names(value: str) -> None:
    parsed = TeamNamePolicy().parse(value)
    assert parsed.value == value
    assert parsed.canonical_key == value.casefold()


@pytest.mark.parametrize("value", ["", ".", "..", "CON", "a/b", "a\\b", "équipe", "x" * 65])
def test_name_policy_rejects_unsafe_names(value: str) -> None:
    with pytest.raises(TeamValidationError):
        TeamNamePolicy().parse(value)


def test_team_paths_are_contained_and_stable(tmp_path) -> None:
    paths = TeamPaths.for_user(tmp_path, TeamNamePolicy().parse("Alpha"))
    paths.ensure_directories()
    assert paths.state_file.parent == tmp_path / "teams" / "Alpha"
    assert paths.mailbox_file("member-1").parent == paths.mailboxes_root
    assert paths.member_control_file("member-1").name == "member-1.control.json"
    assert paths.member_pane_binding_file("member-1").name == "member-1.pane.json"
    assert paths.member_run_file("member-1", "run-2").name == "member-1.run.run-2.json"
    assert paths.member_run_result_file("member-1", "run-2").name == "member-1.run.run-2.result.json"
    with pytest.raises(TeamValidationError):
        paths.mailbox_file("../escape")
    with pytest.raises(TeamValidationError):
        paths.member_run_file("member-1", "../escape")


def test_coordinator_paths_are_separate_and_branch_lock_is_stable(tmp_path) -> None:
    paths = TeamPaths.for_user(tmp_path, TeamNamePolicy().parse("Alpha"))
    paths.ensure_directories()
    assert not paths.coordinator_root.exists()
    paths.ensure_coordinator_directories()
    assert paths.coordinator_settings_file.parent == paths.coordinator_root
    assert paths.coordinator_decomposition_file("run-1").parent == paths.coordinator_decompositions_root
    first = paths.coordinator_branch_lock("repository-1", "refs/heads/main")
    second = paths.coordinator_branch_lock("repository-1", "refs/heads/main")
    assert first == second and first.is_absolute()
    with pytest.raises(TeamValidationError):
        paths.coordinator_decomposition_file("../escape")


def test_coordinator_settings_codec_is_strict_and_versioned() -> None:
    settings = CoordinatorSettings(
        COORDINATOR_SCHEMA_VERSION, True, True, True, COORDINATOR_POLICY_VERSION,
        True, datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    payload = encode_coordinator_settings(settings)
    assert decode_coordinator_settings(payload) == settings
    raw = json.loads(payload)
    raw["schema_version"] = 2
    with pytest.raises(TeamCorruptionError):
        decode_coordinator_settings(json.dumps(raw))
    with pytest.raises(TeamCorruptionError):
        decode_coordinator_settings(payload.decode().replace('"enabled":true', '"enabled":true,"enabled":true'))


def test_models_reject_naive_time(tmp_path) -> None:
    state = empty_state(tmp_path)
    with pytest.raises(TeamValidationError):
        type(state)(**{**state.__dict__, "updated_at": datetime.now()})


def test_team_state_strict_roundtrip(tmp_path) -> None:
    state = empty_state(tmp_path)
    restored = decode_team_state(encode_team_state(state))
    assert restored == state
    assert restored.members == {}


def test_old_member_without_optional_pane_binding_still_loads(tmp_path) -> None:
    state = state_with_members(tmp_path, 1)
    payload = json.loads(encode_team_state(state))
    payload["members"]["member-1"].pop("pane_binding")
    restored = decode_team_state(json.dumps(payload))
    assert restored.members["member-1"].pane_binding is None
    assert restored.members["member-1"].backend is TeamMemberBackend.IN_PROCESS


def test_terminal_binding_strict_roundtrip_and_future_version_rejection() -> None:
    now = FakeClock().now()
    binding = TerminalPaneBinding(
        PANE_BINDING_SCHEMA_VERSION,
        TeamMemberBackend.TMUX,
        "host-1",
        "%9",
        now,
    )
    assert decode_terminal_pane_binding(encode_terminal_pane_binding(binding)) == binding
    payload = json.loads(encode_terminal_pane_binding(binding))
    payload["schema_version"] += 1
    with pytest.raises(TeamCorruptionError):
        decode_terminal_pane_binding(json.dumps(payload))
    payload = json.loads(encode_terminal_pane_binding(binding))
    payload["unknown"] = True
    with pytest.raises(TeamCorruptionError):
        decode_terminal_pane_binding(json.dumps(payload))


def test_codec_rejects_duplicate_unknown_and_nonfinite_fields(tmp_path) -> None:
    state = empty_state(tmp_path)
    value = encode_team_state(state).decode("utf-8")
    with pytest.raises(TeamCorruptionError):
        decode_json('{"a":1,"a":2}')
    with pytest.raises(TeamCorruptionError):
        decode_json('{"value":NaN}')
    payload = __import__("json").loads(value)
    payload["unknown"] = True
    with pytest.raises(TeamCorruptionError):
        decode_team_state(__import__("json").dumps(payload))
