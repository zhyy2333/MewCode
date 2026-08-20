from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import shutil
import sys

from .models import MemberBackendRequest, TeamMemberBackend, TeamValidationError


@dataclass(frozen=True)
class BackendCapability:
    backend: TeamMemberBackend
    available: bool
    reason: str | None = None


class MemberBackendResolver:
    """Resolve member backend requests without allowing silent fallback."""

    def __init__(
        self,
        *,
        platform: Callable[[], str] = lambda: sys.platform,
        environment: Callable[[], Mapping[str, str]] = lambda: os.environ,
        executable: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._platform = platform
        self._environment = environment
        self._executable = executable

    def resolve(self, requested: str | MemberBackendRequest) -> TeamMemberBackend:
        try:
            choice = MemberBackendRequest(requested)
        except ValueError as exc:
            raise TeamValidationError("Unknown team member backend.") from exc
        if choice is MemberBackendRequest.AUTO:
            for candidate in self._automatic_candidates():
                capability = self.probe(candidate)
                if capability.available:
                    return candidate
            raise TeamValidationError("No team member backend is available.")
        selected = TeamMemberBackend(choice.value)
        capability = self.probe(selected)
        if capability.available:
            return selected
        raise TeamValidationError(
            f"Requested team member backend '{selected.value}' is unavailable: "
            f"{capability.reason or 'unsupported environment.'}"
        )

    def probe(self, backend: TeamMemberBackend) -> BackendCapability:
        platform = self._platform().lower()
        environment = self._environment()
        if backend is TeamMemberBackend.IN_PROCESS:
            return BackendCapability(backend, True)
        if backend is TeamMemberBackend.WINDOWS_TERMINAL:
            if not platform.startswith("win"):
                return BackendCapability(backend, False, "Windows Terminal requires Windows.")
            if not environment.get("WT_SESSION"):
                return BackendCapability(backend, False, "Lead is not running in Windows Terminal.")
            if not self._executable("wt"):
                return BackendCapability(backend, False, "The wt executable is unavailable.")
            return BackendCapability(backend, True)
        if backend is TeamMemberBackend.TMUX:
            if not (platform.startswith("linux") or platform.startswith("darwin")):
                return BackendCapability(backend, False, "tmux is supported only on macOS or Linux.")
            if not environment.get("TMUX"):
                return BackendCapability(backend, False, "Lead is not running in tmux.")
            if not self._executable("tmux"):
                return BackendCapability(backend, False, "The tmux executable is unavailable.")
            return BackendCapability(backend, True)
        raise TeamValidationError("Unknown team member backend.")

    def _automatic_candidates(self) -> tuple[TeamMemberBackend, ...]:
        platform = self._platform().lower()
        if platform.startswith("win"):
            return TeamMemberBackend.WINDOWS_TERMINAL, TeamMemberBackend.IN_PROCESS
        if platform.startswith("linux") or platform.startswith("darwin"):
            return TeamMemberBackend.TMUX, TeamMemberBackend.IN_PROCESS
        return (TeamMemberBackend.IN_PROCESS,)
