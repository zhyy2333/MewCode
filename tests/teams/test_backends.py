from __future__ import annotations

import pytest

from mewcode.teams.backends import MemberBackendResolver
from mewcode.teams.models import TeamMemberBackend, TeamValidationError


def _resolver(platform: str, environment: dict[str, str], executables: set[str]):
    return MemberBackendResolver(
        platform=lambda: platform,
        environment=lambda: environment,
        executable=lambda value: value if value in executables else None,
    )


def test_auto_prefers_supported_platform_terminal_then_in_process() -> None:
    assert _resolver("win32", {"WT_SESSION": "session"}, {"wt"}).resolve("auto") is TeamMemberBackend.WINDOWS_TERMINAL
    assert _resolver("win32", {}, {"wt"}).resolve("auto") is TeamMemberBackend.IN_PROCESS
    assert _resolver("linux", {"TMUX": "socket,1,0"}, {"tmux"}).resolve("auto") is TeamMemberBackend.TMUX
    assert _resolver("darwin", {}, {"tmux"}).resolve("auto") is TeamMemberBackend.IN_PROCESS


def test_explicit_backend_never_falls_back() -> None:
    resolver = _resolver("linux", {}, {"tmux"})
    with pytest.raises(TeamValidationError, match="Requested team member backend 'tmux' is unavailable"):
        resolver.resolve("tmux")
    with pytest.raises(TeamValidationError, match="Windows Terminal requires Windows"):
        resolver.resolve("windows_terminal")
    assert resolver.resolve("in_process") is TeamMemberBackend.IN_PROCESS


def test_unknown_request_is_rejected() -> None:
    with pytest.raises(TeamValidationError, match="Unknown team member backend"):
        _resolver("linux", {}, set()).resolve("other")
