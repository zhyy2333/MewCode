from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mewcode.teams.coordinator_models import (
    COORDINATOR_POLICY_VERSION,
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorJournal,
    CoordinatorJournalEntry,
    CoordinatorSettings,
    CoordinatorTaskSpec,
    DecompositionRun,
    DecompositionStatus,
    DeliveryKind,
    JournalBoundary,
)
from mewcode.teams.models import TeamValidationError


NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)
OID_A = "a" * 40


def task(local_id: str = "a", task_id: str = "task-a", dependencies=()) -> CoordinatorTaskSpec:
    local_dependencies = tuple(item[0] for item in dependencies)
    task_dependencies = tuple(item[1] for item in dependencies)
    return CoordinatorTaskSpec(
        local_id,
        task_id,
        0 if local_id == "a" else 1,
        "Title",
        "Description",
        local_dependencies,
        task_dependencies,
        None,
        "coder",
        ("write_file",),
        ("Tests pass",),
        DeliveryKind.GIT,
    )


def test_settings_require_both_switches() -> None:
    settings = CoordinatorSettings(
        COORDINATOR_SCHEMA_VERSION, True, True, True,
        COORDINATOR_POLICY_VERSION, True, NOW,
    )
    assert settings.enabled
    with pytest.raises(TeamValidationError, match="both switches"):
        replace(settings, environment_enabled=False)


def test_decomposition_validates_dependency_mapping_and_cycles() -> None:
    first = task()
    second = task("b", "task-b", (("a", "task-a"),))
    run = DecompositionRun(
        COORDINATOR_SCHEMA_VERSION, 0, "run-1", "team-1", "Ship it",
        "refs/heads/main", OID_A, True, (first, second), (),
        DecompositionStatus.PREPARED, None, NOW, NOW,
    )
    assert run.tasks[1].dependency_task_ids == ("task-a",)
    cyclic_first = replace(first, dependency_local_ids=("b",), dependency_task_ids=("task-b",))
    with pytest.raises(TeamValidationError, match="cycle"):
        replace(run, tasks=(cyclic_first, second))


def test_journal_requires_contiguous_legal_boundaries() -> None:
    prepared = CoordinatorJournalEntry(0, JournalBoundary.PREPARED, None, None, None, None, NOW)
    journal = CoordinatorJournal(
        COORDINATOR_SCHEMA_VERSION, 0, "journal-1", "team-1", "decompose", "run-1", (prepared,)
    )
    completed = CoordinatorJournalEntry(1, JournalBoundary.COMPLETED, None, None, None, None, NOW)
    assert journal.appended(completed).revision == 1
    with pytest.raises(TeamValidationError, match="sequence"):
        journal.appended(replace(completed, sequence=3))
