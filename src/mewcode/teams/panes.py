from __future__ import annotations

from collections.abc import Awaitable, Callable
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import Protocol

from .backends import BackendCapability, MemberBackendResolver
from .control import MemberControlBroker
from .models import PANE_BINDING_SCHEMA_VERSION, PaneHealth, TeamMemberBackend, TeamMemberRecord, TerminalPaneBinding, TeamValidationError, require_identifier


@dataclass(frozen=True)
class PaneHostLaunch:
    host_id: str
    command: tuple[str, ...]
    working_directory: Path

    def __post_init__(self) -> None:
        require_identifier(self.host_id, "host_id")
        command = tuple(self.command)
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise TeamValidationError("Pane host command is invalid.")
        if any("\x00" in item for item in command):
            raise TeamValidationError("Pane host command is invalid.")
        root = Path(self.working_directory)
        if not root.is_absolute():
            raise TeamValidationError("Pane host working directory must be absolute.")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "working_directory", root)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class PendingPane:
    backend: TeamMemberBackend
    host_id: str
    backend_handle: str | None = None


class TerminalPaneAdapter(Protocol):
    backend: TeamMemberBackend

    def probe(self) -> BackendCapability: ...
    async def create_host(self, launch: PaneHostLaunch) -> PendingPane: ...
    async def terminate_unpublished(self, pane: PendingPane) -> None: ...


ProcessRunner = Callable[[tuple[str, ...]], Awaitable[ProcessResult]]
_TMUX_PANE_HANDLE = re.compile(r"^%[1-9][0-9]*$")


async def run_process(argv: tuple[str, ...]) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return ProcessResult(
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


class _BasePaneAdapter:
    def __init__(self, resolver: MemberBackendResolver, runner: ProcessRunner) -> None:
        self._resolver = resolver
        self._runner = runner

    def probe(self) -> BackendCapability:
        return self._resolver.probe(self.backend)

    async def _run(self, argv: tuple[str, ...]) -> ProcessResult:
        result = await self._runner(argv)
        if result.returncode != 0:
            raise TeamValidationError(
                f"Unable to create {self.backend.value} pane: terminal command exited "
                f"with code {result.returncode}."
            )
        return result


class WindowsTerminalPaneAdapter(_BasePaneAdapter):
    backend = TeamMemberBackend.WINDOWS_TERMINAL

    async def create_host(self, launch: PaneHostLaunch) -> PendingPane:
        self._require_available()
        argv = (
            "wt", "--window", "0", "split-pane",
            "--title", f"MewCode member {launch.host_id}",
            "--startingDirectory", str(launch.working_directory),
            *launch.command,
        )
        await self._run(argv)
        return PendingPane(self.backend, launch.host_id)

    async def terminate_unpublished(self, pane: PendingPane) -> None:
        if pane.backend is not self.backend:
            raise TeamValidationError("Pane backend does not match adapter.")
        # Windows Terminal does not expose a stable pane handle; the registered host
        # receives the cleanup request once it becomes reachable.

    def _require_available(self) -> None:
        capability = self.probe()
        if not capability.available:
            raise TeamValidationError(
                f"Requested team member backend '{self.backend.value}' is unavailable: "
                f"{capability.reason or 'unsupported environment.'}"
            )


class TmuxPaneAdapter(_BasePaneAdapter):
    backend = TeamMemberBackend.TMUX

    async def create_host(self, launch: PaneHostLaunch) -> PendingPane:
        self._require_available()
        result = await self._run((
            "tmux", "split-window", "-P", "-F", "#{pane_id}",
            "-c", str(launch.working_directory), *launch.command,
        ))
        handle = result.stdout.strip()
        if _TMUX_PANE_HANDLE.fullmatch(handle) is None:
            raise TeamValidationError("tmux did not return a valid pane handle.")
        return PendingPane(self.backend, launch.host_id, handle)

    async def terminate_unpublished(self, pane: PendingPane) -> None:
        if pane.backend is not self.backend:
            raise TeamValidationError("Pane backend does not match adapter.")
        if pane.backend_handle:
            await self._run(("tmux", "kill-pane", "-t", pane.backend_handle))

    def _require_available(self) -> None:
        capability = self.probe()
        if not capability.available:
            raise TeamValidationError(
                f"Requested team member backend '{self.backend.value}' is unavailable: "
                f"{capability.reason or 'unsupported environment.'}"
            )


class TerminalHostProvisioner:
    """Creates a real pane only after its loopback host registers with the Lead."""

    def __init__(
        self,
        broker: MemberControlBroker,
        adapters: dict[TeamMemberBackend, TerminalPaneAdapter],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        registration_timeout: float = 10.0,
        command: tuple[str, ...] | None = None,
    ) -> None:
        self._broker = broker
        self._adapters = adapters
        self._now = now
        self._registration_timeout = registration_timeout
        self._command = command or (sys.executable, "-m", "mewcode", "--team-pane-host")
        if registration_timeout <= 0:
            raise TeamValidationError("Pane host registration timeout is invalid.")

    async def provision(self, team_id: str, member: TeamMemberRecord) -> TerminalPaneBinding:
        if member.backend is TeamMemberBackend.IN_PROCESS:
            raise TeamValidationError("In-process members do not require a terminal host.")
        adapter = self._adapters.get(member.backend)
        if adapter is None:
            raise TeamValidationError(f"Requested team member backend '{member.backend.value}' is unavailable: no pane adapter is configured.")
        host_id = await self._broker.authorize_pending(member.member_id)
        control_file = self._broker.descriptor_path(member.member_id)
        pane: PendingPane | None = None
        try:
            launch = PaneHostLaunch(host_id, (*self._command, "--control-file", str(control_file)), member.worktree_root)
            pane = await adapter.create_host(launch)
            connection = await self._broker.wait_for_connection(member.member_id, host_id, timeout=self._registration_timeout)
            del connection
            return TerminalPaneBinding(
                PANE_BINDING_SCHEMA_VERSION, member.backend, host_id, pane.backend_handle,
                self._now(), self._now(), None,
            )
        except BaseException:
            if pane is not None:
                await adapter.terminate_unpublished(pane)
            self._broker.descriptor_path(member.member_id).unlink(missing_ok=True)
            raise

    async def terminate(self, binding: TerminalPaneBinding) -> None:
        await self._broker.shutdown_host(binding.host_id)
        adapter = self._adapters.get(binding.backend)
        if adapter is None:
            raise TeamValidationError("Terminal pane adapter is unavailable for cleanup.")
        await adapter.terminate_unpublished(PendingPane(binding.backend, binding.host_id, binding.backend_handle))

    def health(self, member_id: str) -> PaneHealth:
        return self._broker.health(member_id)
