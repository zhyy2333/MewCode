from __future__ import annotations

from collections.abc import Callable
from datetime import date
import os
from pathlib import Path
import platform

from .models import PromptEnvironment


class PromptEnvironmentProvider:
    def __init__(
        self,
        workspace_root: str | Path,
        *,
        clock: Callable[[], date] | None = None,
        operating_system: Callable[[], str] | None = None,
        shell: str | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._clock = clock or date.today
        self._operating_system = operating_system or platform.system
        self._shell = shell

    def get(self) -> PromptEnvironment:
        operating_system = self._operating_system().strip() or "unknown"
        return PromptEnvironment(
            workspace_root=str(self._workspace_root),
            operating_system=operating_system,
            current_date=self._clock().isoformat(),
            shell=self._resolve_shell(operating_system),
        )

    def _resolve_shell(self, operating_system: str) -> str:
        if operating_system.casefold() == "windows":
            return "PowerShell"
        shell = self._shell
        if shell is None:
            shell = os.environ.get("SHELL", "")
        shell_name = Path(shell).name.strip()
        return shell_name or "unknown"


def render_environment(environment: PromptEnvironment) -> str:
    return "\n".join(
        (
            f"Workspace: {environment.workspace_root}",
            f"Operating system: {environment.operating_system}",
            f"Current date: {environment.current_date}",
            f"Shell: {environment.shell}",
        )
    )
