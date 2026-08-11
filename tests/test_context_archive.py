from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest

from mewcode.context import ArchiveKind, ContextArchive, ContextArchiveError
from mewcode.context import archive as archive_module
from mewcode.providers import ChatMessage
from mewcode.tools import ToolExecution, ToolResult

from tests.fakes import tool_call


def execution(content: str = "result") -> ToolExecution:
    return ToolExecution(
        index=0,
        request=tool_call("call-1", "read_file", path="example.py"),
        result=ToolResult(True, "read_file", content, metadata={"line": 1}),
    )


def test_archive_writes_atomic_readable_records_and_deletes_on_close(
    tmp_path: Path,
) -> None:
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "current")
    assert archive.start() == ()

    tool_record = archive.write_tool_result(execution("猫" * 100))
    history_record = archive.write_history([ChatMessage("user", "keep verbatim")])
    tool_path = tmp_path / tool_record.relative_path
    history_path = tmp_path / history_record.relative_path

    assert tool_record.kind is ArchiveKind.TOOL_RESULT
    assert history_record.kind is ArchiveKind.HISTORY
    assert json.loads(tool_path.read_text(encoding="utf-8"))["execution"]["result"][
        "content"
    ] == "猫" * 100
    assert json.loads(history_path.read_text(encoding="utf-8"))["messages"][0][
        "content"
    ] == "keep verbatim"
    assert not list(tool_path.parent.glob("*.tmp"))

    session_dir = archive.session_dir
    assert archive.close() == ()
    assert session_dir is not None
    assert not session_dir.exists()


def test_start_removes_stale_directory_but_preserves_locked_active_session(
    tmp_path: Path,
) -> None:
    stale = tmp_path / ".mewcode" / "context" / "stale"
    stale.mkdir(parents=True)
    (stale / ".active.lock").write_bytes(b"1")
    (stale / "orphan.json").write_text("{}", encoding="utf-8")

    active = ContextArchive(tmp_path, session_id_factory=lambda: "active")
    active.start()
    active_dir = active.session_dir
    newcomer = ContextArchive(tmp_path, session_id_factory=lambda: "new")
    newcomer.start()

    assert not stale.exists()
    assert active_dir is not None and active_dir.exists()

    newcomer.close()
    active.close()


def test_discard_only_accepts_records_from_the_active_session(tmp_path: Path) -> None:
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "current")
    archive.start()
    record = archive.write_tool_result(execution())

    assert archive.discard(record) is None
    assert not (tmp_path / record.relative_path).exists()

    archive.close()


def test_atomic_publish_failure_leaves_no_record_or_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "current")
    archive.start()
    monkeypatch.setattr(
        archive_module.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("blocked")),
    )

    with pytest.raises(ContextArchiveError, match="Unable to archive"):
        archive.write_tool_result(execution("secret payload"))

    assert archive.session_dir is not None
    assert list(archive.session_dir.glob("tool-*.json")) == []
    assert list(archive.session_dir.glob("*.tmp")) == []
    archive.close()


def test_cleanup_failure_warns_and_continues_with_other_stale_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".mewcode" / "context"
    bad = root / "bad"
    good = root / "good"
    for directory in (bad, good):
        directory.mkdir(parents=True)
        (directory / ".active.lock").write_bytes(b"1")
    real_rmtree = archive_module.shutil.rmtree

    def selective_failure(path, *args, **kwargs):
        if Path(path).name == "bad":
            raise OSError("blocked")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(archive_module.shutil, "rmtree", selective_failure)
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "current")

    warnings = archive.start()

    assert len(warnings) == 1
    assert "payload" not in warnings[0].message
    assert bad.exists()
    assert not good.exists()
    archive.close()


@pytest.mark.skipif(archive_module.os.name != "nt", reason="Windows-only lock branch")
def test_windows_lock_branch_rejects_a_second_active_session(tmp_path: Path) -> None:
    first = ContextArchive(tmp_path, session_id_factory=lambda: "first")
    first.start()
    second = ContextArchive(tmp_path, session_id_factory=lambda: "second")
    second.start()

    assert first.session_dir is not None and first.session_dir.exists()
    second.close()
    first.close()


def test_unix_lock_branch_uses_nonblocking_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    fake_fcntl = types.SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda _fileno, operation: calls.append(operation),
    )
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    monkeypatch.setattr(archive_module.os, "name", "posix")
    handle = (tmp_path / "lock").open("a+b")
    lock = archive_module._SessionLock(handle)

    assert lock.acquire() is True
    lock.close()

    assert calls == [3, 4]
