from __future__ import annotations

import json
from pathlib import Path

from mewcode.context import ArchiveKind, ContextArchive
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
