from __future__ import annotations

from datetime import datetime

import pytest

from mewcode.teams.models import TeamValidationError
from mewcode.teams.codec import decode_json, decode_team_state, encode_team_state
from mewcode.teams.models import TeamCorruptionError
from mewcode.teams.paths import TeamNamePolicy, TeamPaths

from .helpers import empty_state


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
    with pytest.raises(TeamValidationError):
        paths.mailbox_file("../escape")


def test_models_reject_naive_time(tmp_path) -> None:
    state = empty_state(tmp_path)
    with pytest.raises(TeamValidationError):
        type(state)(**{**state.__dict__, "updated_at": datetime.now()})


def test_team_state_strict_roundtrip(tmp_path) -> None:
    state = empty_state(tmp_path)
    restored = decode_team_state(encode_team_state(state))
    assert restored == state
    assert restored.members == {}


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
