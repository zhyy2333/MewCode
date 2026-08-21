from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path

from mewcode.config import DEFAULT_CONFIG_PATH, load_coordinator_configuration_enabled

from .coordinator_models import (
    COORDINATOR_POLICY_VERSION,
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorSettings,
)


COORDINATOR_ENVIRONMENT_VARIABLE = "MEWCODE_ENABLE_TEAM_COORDINATOR"


@dataclass(frozen=True)
class CoordinatorSettingsResult:
    settings: CoordinatorSettings
    diagnostic: str | None = None


class TerminalBackendReadiness:
    """Build capability shipped after Phase 14B acceptance."""

    def verified(self) -> bool:
        return True


class CoordinatorSettingsResolver:
    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        configuration: Callable[[Path], bool] = load_coordinator_configuration_enabled,
        readiness: TerminalBackendReadiness | Callable[[], bool] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._environment = environment if environment is not None else os.environ
        self._configuration = configuration
        self._readiness = readiness or TerminalBackendReadiness()
        self._now = now

    def resolve(self, config_path: Path = DEFAULT_CONFIG_PATH) -> CoordinatorSettingsResult:
        configured = self._configuration(Path(config_path))
        raw = self._environment.get(COORDINATOR_ENVIRONMENT_VARIABLE)
        diagnostic = None
        if raw == "1":
            environment_enabled = True
        elif raw in {None, "", "0"}:
            environment_enabled = False
        else:
            environment_enabled = False
            diagnostic = (
                f"{COORDINATOR_ENVIRONMENT_VARIABLE} must be exactly 1 to enable "
                "team coordinator mode; coordinator remains disabled."
            )
        readiness = self._readiness
        terminal_verified = (
            bool(readiness()) if callable(readiness) else bool(readiness.verified())
        )
        settings = CoordinatorSettings(
            COORDINATOR_SCHEMA_VERSION,
            configured,
            environment_enabled,
            configured and environment_enabled,
            COORDINATOR_POLICY_VERSION,
            terminal_verified,
            self._now(),
        )
        return CoordinatorSettingsResult(settings, diagnostic)
