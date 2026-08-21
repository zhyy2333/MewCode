from dataclasses import replace
from datetime import datetime, timezone

import pytest

from mewcode.teams.coordinator_models import (
    COORDINATOR_POLICY_VERSION,
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorSettings,
    CoordinatorTaskSpec,
    DecompositionRun,
    DecompositionStatus,
    DeliveryKind,
    CoordinatorJournal,
    CoordinatorJournalEntry,
    JournalBoundary,
)
from mewcode.teams.coordinator_repository import CoordinatorRepository
from mewcode.teams.models import TeamConflictError, TeamCorruptionError, TeamValidationError
from mewcode.teams.repository import TeamRepository

from .helpers import empty_state, team_name


NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)
OID = "a" * 40


def settings(enabled: bool = True) -> CoordinatorSettings:
    return CoordinatorSettings(
        COORDINATOR_SCHEMA_VERSION, enabled, enabled, enabled,
        COORDINATOR_POLICY_VERSION, True, NOW,
    )


def run(revision: int = 0) -> DecompositionRun:
    spec = CoordinatorTaskSpec(
        "a", "task-a", 0, "Title", "Description", (), (), None, "coder", (),
        ("Done",), DeliveryKind.GIT,
    )
    return DecompositionRun(
        COORDINATOR_SCHEMA_VERSION, revision, "run-1", "team-1", "Goal",
        "refs/heads/main", OID, True, (spec,), (), DecompositionStatus.PREPARED,
        None, NOW, NOW,
    )


def repository(tmp_path):
    teams = TeamRepository(tmp_path)
    teams.create(empty_state(tmp_path))
    return CoordinatorRepository(teams, team_name())


def test_disabled_initialize_creates_no_coordinator_directory(tmp_path) -> None:
    store = repository(tmp_path)
    with pytest.raises(TeamValidationError, match="Disabled"):
        store.initialize(settings(False))
    assert not store.paths.coordinator_root.exists()


def test_decomposition_create_load_and_cas(tmp_path) -> None:
    store = repository(tmp_path)
    store.initialize(settings())
    store.create_decomposition(run())
    assert store.load_decomposition("run-1") == run()
    updated = replace(run(), revision=1, status=DecompositionStatus.ACTIVE)
    assert store.update_decomposition(updated, expected_revision=0) == updated
    with pytest.raises(TeamConflictError, match="revision"):
        store.update_decomposition(replace(updated, revision=2), expected_revision=0)


def test_truncated_record_is_rejected_without_rewrite(tmp_path) -> None:
    store = repository(tmp_path)
    store.initialize(settings())
    store.create_decomposition(run())
    path = store.paths.coordinator_decomposition_file("run-1")
    path.write_bytes(b'{"partial":')
    before = path.read_bytes()
    with pytest.raises(TeamCorruptionError):
        store.load_decomposition("run-1")
    assert path.read_bytes() == before


def test_journal_append_and_branch_lock_are_serialized(tmp_path) -> None:
    store = repository(tmp_path)
    store.initialize(settings())
    journal = CoordinatorJournal(
        COORDINATOR_SCHEMA_VERSION,
        0,
        "journal-1",
        "team-1",
        "decomposition",
        "run-1",
        (CoordinatorJournalEntry(0, JournalBoundary.PREPARED, None, None, None, None, NOW),),
    )
    store.create_journal(journal)
    appended = store.append_journal(
        "journal-1",
        CoordinatorJournalEntry(1, JournalBoundary.TEAM_STATE_COMMITTED, None, None, None, None, NOW),
    )
    assert appended.revision == 1 and len(appended.entries) == 2

    with store.branch_lock("repository-1", "refs/heads/main"):
        with pytest.raises(TeamConflictError, match="busy"):
            with store.branch_lock("repository-1", "refs/heads/main"):
                pass
        with store.branch_lock("repository-1", "refs/heads/release"):
            pass
