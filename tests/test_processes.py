from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pytest

from mewcode.processes import ProcessRequest, merge_process_environment, run_shell


def _python(code: str) -> str:
    escaped = code.replace('"', '\\"')
    return f'{sys.executable} -c "{escaped}"'


def test_stdin_stdout_stderr_and_exit(tmp_path: Path) -> None:
    async def scenario():
        return await run_shell(
            ProcessRequest(
                _python("import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data); sys.stderr.write('err'); sys.exit(7)"),
                tmp_path,
                stdin=b"hello",
                timeout_seconds=5,
            )
        )

    result = asyncio.run(scenario())
    assert result.exit_code == 7
    assert result.stdout == b"hello"
    assert result.stderr == b"err"


def test_output_limit_terminates_process(tmp_path: Path) -> None:
    result = asyncio.run(
        run_shell(
            ProcessRequest(
                _python("import sys,time; sys.stdout.write('x'*10000); sys.stdout.flush(); time.sleep(2)"),
                tmp_path,
                stdout_limit=100,
                timeout_seconds=5,
            )
        )
    )
    assert result.stdout_exceeded
    assert len(result.stdout) == 100


def test_timeout(tmp_path: Path) -> None:
    result = asyncio.run(
        run_shell(
            ProcessRequest(_python("import time; time.sleep(5)"), tmp_path, timeout_seconds=0.1)
        )
    )
    assert result.timed_out


def test_cancel_stops_child(tmp_path: Path) -> None:
    async def scenario() -> None:
        task = asyncio.create_task(
            run_shell(
                ProcessRequest(
                    _python("import time; from pathlib import Path; time.sleep(1); Path('alive').write_text('x')"),
                    tmp_path,
                )
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(1.1)
        assert not (tmp_path / "alive").exists()

    asyncio.run(scenario())


def test_merge_process_environment_is_child_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEWCODE_PARENT", "kept")
    root = tmp_path.resolve()
    result = merge_process_environment(
        {"MEWCODE_PARENT": "kept"},
        overrides={"TASK": "one"},
        workspace_root=root,
        git_config=(("core.hooksPath", ".githooks"),),
    )
    assert result["MEWCODE_WORKSPACE_ROOT"] == str(root)
    assert result["GIT_CONFIG_COUNT"] == "1"
    assert result["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    assert result["GIT_CONFIG_VALUE_0"] == ".githooks"
    assert "TASK" not in os.environ


def test_merge_process_environment_rejects_malformed_git_config() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        merge_process_environment({"GIT_CONFIG_COUNT": "1"})
