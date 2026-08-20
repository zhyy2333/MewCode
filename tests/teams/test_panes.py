from __future__ import annotations

import asyncio

import pytest

from mewcode.teams.backends import MemberBackendResolver
from mewcode.teams.models import TeamMemberBackend, TeamValidationError
from mewcode.teams.panes import (
    PaneHostLaunch,
    ProcessResult,
    TmuxPaneAdapter,
    WindowsTerminalPaneAdapter,
)


def _resolver(platform: str, environment: dict[str, str], executables: set[str]):
    return MemberBackendResolver(
        platform=lambda: platform,
        environment=lambda: environment,
        executable=lambda value: value if value in executables else None,
    )


class _Runner:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, argv: tuple[str, ...]) -> ProcessResult:
        self.calls.append(argv)
        return self.result


def test_windows_terminal_uses_fixed_argv_and_requires_host(tmp_path) -> None:
    async def scenario() -> None:
        runner = _Runner(ProcessResult(0))
        adapter = WindowsTerminalPaneAdapter(
            _resolver("win32", {"WT_SESSION": "current"}, {"wt"}), runner,
        )
        pane = await adapter.create_host(PaneHostLaunch("host-1", ("mewcode", "--member-host"), tmp_path))
        assert pane.backend is TeamMemberBackend.WINDOWS_TERMINAL
        assert runner.calls == [
            ("wt", "--window", "0", "split-pane", "--title", "MewCode member host-1", "--startingDirectory", str(tmp_path), "mewcode", "--member-host")
        ]
    asyncio.run(scenario())


def test_tmux_returns_handle_and_can_clean_unpublished_pane(tmp_path) -> None:
    async def scenario() -> None:
        runner = _Runner(ProcessResult(0, "%11\n"))
        adapter = TmuxPaneAdapter(_resolver("linux", {"TMUX": "socket"}, {"tmux"}), runner)
        pane = await adapter.create_host(PaneHostLaunch("host-1", ("mewcode", "--member-host"), tmp_path))
        assert pane.backend_handle == "%11"
        await adapter.terminate_unpublished(pane)
        assert runner.calls[-1] == ("tmux", "kill-pane", "-t", "%11")
    asyncio.run(scenario())


def test_adapter_rejects_unavailable_host_and_invalid_tmux_response(tmp_path) -> None:
    async def scenario() -> None:
        runner = _Runner(ProcessResult(0, "bad\nextra\n"))
        windows = WindowsTerminalPaneAdapter(_resolver("win32", {}, {"wt"}), runner)
        with pytest.raises(TeamValidationError, match="not running in Windows Terminal"):
            await windows.create_host(PaneHostLaunch("host-1", ("mewcode",), tmp_path))
        tmux = TmuxPaneAdapter(_resolver("linux", {"TMUX": "socket"}, {"tmux"}), runner)
        with pytest.raises(TeamValidationError, match="valid pane handle"):
            await tmux.create_host(PaneHostLaunch("host-1", ("mewcode",), tmp_path))
    asyncio.run(scenario())


def test_adapter_diagnostic_does_not_echo_terminal_stderr(tmp_path) -> None:
    async def scenario() -> None:
        runner = _Runner(ProcessResult(7, stderr="secret-token"))
        adapter = TmuxPaneAdapter(_resolver("linux", {"TMUX": "socket"}, {"tmux"}), runner)
        with pytest.raises(TeamValidationError) as captured:
            await adapter.create_host(PaneHostLaunch("host-1", ("mewcode",), tmp_path))
        assert "code 7" in str(captured.value)
        assert "secret-token" not in str(captured.value)
    asyncio.run(scenario())
