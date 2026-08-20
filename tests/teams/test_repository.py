from __future__ import annotations

from dataclasses import replace

import pytest

from mewcode.teams.codec import encode_lead_lease
from mewcode.teams.models import (
    SCHEMA_VERSION,
    TeamConflictError,
    TeamCorruptionError,
    TeamLeadLeaseRecord,
)
from mewcode.teams.repository import (
    TeamProvisioningJournalStore,
    TeamRepository,
    atomic_write,
)

from .helpers import FakeClock, empty_state, team_name


def test_repository_create_list_and_load_across_instances(tmp_path) -> None:
    state = empty_state(tmp_path)
    first = TeamRepository(tmp_path)
    first.create(state)
    second = TeamRepository(tmp_path)
    assert second.load(team_name()) == state
    assert second.list()[0].team_id == state.manifest.team_id
    with pytest.raises(TeamConflictError):
        second.create(state)


def test_repository_cas_checks_revision_and_fence(tmp_path) -> None:
    clock = FakeClock()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(empty_state(tmp_path, clock))
    paths = repository.paths(state.manifest.name)
    lease = TeamLeadLeaseRecord(
        schema_version=SCHEMA_VERSION,
        team_id=state.manifest.team_id,
        lease_id="lease-1",
        generation=1,
        holder_session_id="session-1",
        holder_process_id="process-1",
        heartbeat_at=clock.now(),
    )
    atomic_write(paths.lease_file, encode_lead_lease(lease))
    committed = repository.compare_and_swap(
        state.manifest.name,
        expected_revision=0,
        lease_fence=("lease-1", 1),
        candidate=state,
    )
    assert committed.revision == 1
    with pytest.raises(TeamConflictError):
        repository.compare_and_swap(
            state.manifest.name,
            expected_revision=0,
            lease_fence=("lease-1", 1),
            candidate=state,
        )


def test_corrupt_state_is_preserved(tmp_path) -> None:
    repository = TeamRepository(tmp_path)
    state = repository.create(empty_state(tmp_path))
    path = repository.paths(state.manifest.name).state_file
    path.write_bytes(b'{"broken":')
    before = path.read_bytes()
    with pytest.raises(TeamCorruptionError):
        repository.load(state.manifest.name)
    assert path.read_bytes() == before


def test_journal_roundtrip_and_delete(tmp_path) -> None:
    repository = TeamRepository(tmp_path)
    state = repository.create(empty_state(tmp_path))
    store = TeamProvisioningJournalStore(repository, state.manifest.name)
    store.write("tx-1", {"kind": "member", "stage": 2})
    assert store.list() == (("tx-1", {"kind": "member", "stage": 2}),)
    store.delete("tx-1")
    assert store.list() == ()
