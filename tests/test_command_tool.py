from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from mewcode.tools.command_tool import RunCommandTool
from mewcode.tools.workspace import Workspace


def run_tool(tool, arguments: dict[str, Any]):
    return asyncio.run(tool.execute(arguments))


def test_run_command_executes_safe_command(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path)),
        {"command": f'{sys.executable} -c "print(123)"'}
    )

    assert result.ok is True
    assert result.metadata["exit_code"] == 0
    assert result.metadata["stdout"].strip() == "123"


def test_run_command_reports_nonzero_exit_code(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path)),
        {"command": f'{sys.executable} -c "import sys; sys.exit(7)"'}
    )

    assert result.ok is False
    assert result.metadata["exit_code"] == 7
    assert "7" in (result.error or "")


def test_run_command_uses_workspace_cwd(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("x", encoding="utf-8")
    result = run_tool(RunCommandTool(Workspace(tmp_path)),
        {"command": f'{sys.executable} -c "from pathlib import Path; print(Path.cwd().name)"'}
    )

    assert result.ok is True
    assert result.metadata["stdout"].strip() == tmp_path.name


def test_run_command_times_out(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path)),
        {"command": f'{sys.executable} -c "import time; time.sleep(2)"', "timeout_seconds": 1}
    )

    assert result.ok is False
    assert result.metadata["timed_out"] is True
    assert "timed out" in (result.error or "")


def test_run_command_blocks_dangerous_command(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path)), {"command": "rm -rf /"})

    assert result.ok is False
    assert result.metadata["blocked"] is True


def test_run_command_rejects_invalid_timeout(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path)),
        {"command": "echo hi", "timeout_seconds": 0}
    )

    assert result.ok is False
    assert "positive integer" in (result.error or "")


def test_run_command_rejects_timeout_above_max(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path), max_timeout_seconds=5),
        {"command": "echo hi", "timeout_seconds": 6}
    )

    assert result.ok is False
    assert "must not exceed" in (result.error or "")


def test_run_command_truncates_output(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path), content_limit=3),
        {"command": f'{sys.executable} -c "print(\\"abcdef\\")"'}
    )

    assert result.ok is True
    assert result.metadata["truncated"] is True
    assert result.metadata["stdout"].startswith("abc")


def test_run_command_rejects_empty_command(tmp_path: Path) -> None:
    result = run_tool(RunCommandTool(Workspace(tmp_path)), {"command": " "})

    assert result.ok is False
    assert "empty" in (result.error or "")


def test_run_command_cancel_stops_quickly(tmp_path: Path) -> None:
    async def scenario() -> None:
        tool = RunCommandTool(Workspace(tmp_path))
        marker = tmp_path / "survived.txt"
        task = asyncio.create_task(
            tool.execute(
                {
                    "command": (
                        f'{sys.executable} -c "import time; from pathlib import Path; '
                        "time.sleep(1); Path('survived.txt').write_text('alive')\""
                    )
                }
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        await asyncio.sleep(1.1)
        assert marker.exists() is False

    asyncio.run(scenario())
