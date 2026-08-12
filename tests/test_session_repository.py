from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mewcode.continuity import (
    ContinuityPaths,
    SessionError,
    SessionOpenMode,
    SessionOpenRequest,
    SessionPersistenceError,
    SessionRepository,
    StoredPlan,
    StoredSkillActivation,
)
from mewcode.continuity.session_codec import encode_history, encode_start, replay_file
from mewcode.providers import ChatMessage, MessageKind

NOW = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)


def _repo(tmp_path: Path, suffixes=None) -> SessionRepository:
    workspace = tmp_path / "workspace"
    user = tmp_path / "user"
    workspace.mkdir(exist_ok=True)
    values = iter(suffixes or ["abcd"])
    return SessionRepository(
        ContinuityPaths.for_workspace(workspace, user_root=user),
        clock=lambda: NOW,
        suffix_factory=lambda: next(values),
    )


def test_id_create_and_binding_roundtrip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    assert opened.state.session_id == "20260811-120000-abcd"
    binding = opened.binding
    first = (ChatMessage("user", "hello"),)
    binding.commit_history(first, now=NOW)
    binding.commit_history((*first, ChatMessage("assistant", "done")), now=NOW)
    binding.commit_history((ChatMessage("user", "replacement"),), now=NOW)
    binding.commit_plan(StoredPlan("task", "plan"), now=NOW)
    binding.commit_skills((StoredSkillActivation("review", "focus"),), now=NOW)
    binding.close()
    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, opened.state.session_id))
    assert resumed.state.messages == (ChatMessage("user", "replacement"),)
    assert resumed.state.pending_plan == StoredPlan("task", "plan")
    assert resumed.state.active_skills == (StoredSkillActivation("review", "focus"),)
    resumed.binding.close()


def test_reset_state_atomically_rewrites_same_session(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    session_id = opened.state.session_id
    opened.binding.commit_history((ChatMessage("user", "old"),), now=NOW)
    opened.binding.commit_plan(StoredPlan("task", "plan"), now=NOW)
    opened.binding.commit_skills((StoredSkillActivation("review", "x"),), now=NOW)
    opened.binding.reset_state(now=NOW + timedelta(minutes=1))
    opened.binding.close()

    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW + timedelta(minutes=2))
    assert resumed.state.session_id == session_id
    assert resumed.state.messages == ()
    assert resumed.state.pending_plan is None
    assert resumed.state.active_skills == ()
    resumed.binding.close()


def test_same_second_collision_retries(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ["abcd", "abcd", "ef01"])
    first = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    second = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    assert first.state.session_id != second.state.session_id
    first.binding.close()
    second.binding.close()


def test_lock_blocks_explicit_resume(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    with pytest.raises(SessionError, match="active"):
        repo.open(SessionOpenRequest(SessionOpenMode.RESUME, opened.state.session_id))
    opened.binding.close()
    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, opened.state.session_id))
    resumed.binding.close()


def test_auto_uses_latest_recoverable(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ["aaaa", "bbbb", "cccc"])
    first = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW - timedelta(days=2))
    first.binding.commit_history((ChatMessage("user", "older"),), now=NOW - timedelta(days=2))
    first.binding.close()
    second = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW - timedelta(days=1))
    second.binding.commit_history((ChatMessage("user", "newer"),), now=NOW - timedelta(days=1))
    second.binding.close()
    auto = repo.open(SessionOpenRequest(), NOW)
    assert auto.state.session_id == second.state.session_id
    auto.binding.close()


def test_explicit_missing_expired_and_invalid(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(SessionError):
        repo.open(SessionOpenRequest(SessionOpenMode.RESUME, "20260811-120000-dead"))
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW - timedelta(days=31))
    opened.binding.close()
    with pytest.raises(SessionError, match="expired"):
        repo.open(SessionOpenRequest(SessionOpenMode.RESUME, opened.state.session_id), NOW)


def test_scan_uses_streaming_summary_instead_of_full_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW)
    opened.binding.commit_history((ChatMessage("user", "streaming title"),), now=NOW)
    opened.binding.close()
    monkeypatch.setattr(
        "mewcode.continuity.session_repository.replay_file",
        lambda *args: (_ for _ in ()).throw(AssertionError("full replay not allowed")),
    )

    summaries = repo.scan(NOW)

    assert summaries[0].title == "streaming title"
    assert summaries[0].message_count == 1


def test_partial_tail_and_tool_history_are_repaired(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    session_id = opened.state.session_id
    path = opened.binding._path
    opened.binding.close()
    call = ChatMessage("assistant", {"type": "function_call", "call_id": "1", "name": "x", "arguments": "{}"}, MessageKind.TOOL_CALL, "g")
    with path.open("ab") as handle:
        handle.write(encode_history((ChatMessage("user", "safe"), call), "append", NOW))
        handle.write(b'{"partial"')
    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW)
    assert resumed.state.messages == (ChatMessage("user", "safe"),)
    assert {item.code for item in resumed.diagnostics} >= {"bad_lines_skipped", "history_repaired"}
    resumed.binding.close()
    assert replay_file(path, session_id).messages == (ChatMessage("user", "safe"),)


def test_gap_notice_is_system_and_not_duplicated(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW - timedelta(days=2))
    session_id = opened.state.session_id
    opened.binding.commit_history((ChatMessage("user", "work"),), now=NOW - timedelta(days=2))
    opened.binding.close()
    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW)
    assert resumed.state.messages[-1].kind is MessageKind.RESUME_NOTICE
    assert resumed.state.messages[-1].role == "system"
    resumed.binding.close()
    again = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW)
    assert sum(item.kind is MessageKind.RESUME_NOTICE for item in again.state.messages) == 1
    again.binding.close()


def test_cleanup_is_throttled_and_skips_active(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ["aaaa", "bbbb"])
    old = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW - timedelta(days=31))
    old_path = old.binding._path
    old.binding.close()
    active = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW - timedelta(days=31))
    active_path = active.binding._path
    assert repo.maintain(NOW) == ()
    assert not old_path.exists()
    assert active_path.exists()
    assert repo.maintain(NOW + timedelta(hours=1)) == ()
    active.binding.close()


def test_binding_append_failure_keeps_previous_state(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    before = opened.binding._messages
    monkeypatch.setattr(opened.binding, "_append_record", lambda _payload: (_ for _ in ()).throw(SessionPersistenceError("failed")))
    with pytest.raises(SessionPersistenceError):
        opened.binding.commit_history((ChatMessage("user", "lost"),))
    assert opened.binding._messages == before
    opened.binding.close()
