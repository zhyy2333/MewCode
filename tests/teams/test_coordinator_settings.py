from datetime import datetime, timezone
from pathlib import Path

import pytest

from mewcode.teams.coordinator_settings import CoordinatorSettingsResolver


NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("configured", "environment", "expected"),
    [(False, {}, False), (True, {}, False), (False, {"MEWCODE_ENABLE_TEAM_COORDINATOR": "1"}, False), (True, {"MEWCODE_ENABLE_TEAM_COORDINATOR": "1"}, True)],
)
def test_resolver_requires_both_switches(configured, environment, expected) -> None:
    result = CoordinatorSettingsResolver(
        environment=environment,
        configuration=lambda _path: configured,
        readiness=lambda: True,
        now=lambda: NOW,
    ).resolve(Path("ignored"))
    assert result.settings.enabled is expected


def test_invalid_environment_value_is_disabled_and_not_echoed() -> None:
    secret = "not-valid-secret"
    result = CoordinatorSettingsResolver(
        environment={"MEWCODE_ENABLE_TEAM_COORDINATOR": secret},
        configuration=lambda _path: True,
        readiness=lambda: False,
        now=lambda: NOW,
    ).resolve(Path("ignored"))
    assert not result.settings.enabled
    assert not result.settings.terminal_backends_verified
    assert secret not in (result.diagnostic or "")
