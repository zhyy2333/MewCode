from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest

from mewcode.teams.models import TeamAttachment, TeamLeadLease, TeamLeadLeaseRecord, TeamValidationError
from mewcode.teams.repository_binding import TeamRepositoryBindingService

from .helpers import FakeClock, FakeIds, empty_state


def _git_init(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_repository_binding_verify_and_relink(tmp_path) -> None:
    first = tmp_path / "first"
    other = tmp_path / "other"
    moved = tmp_path / "moved"
    _git_init(first)
    _git_init(other)
    clock = FakeClock()
    service = TeamRepositoryBindingService(now=clock.now, new_id=FakeIds())

    async def scenario() -> None:
        binding = await service.create_binding("team-1", first)
        identity = await service.verify(binding, first)
        assert identity.repository_id == binding.repository_id
        with pytest.raises(TeamValidationError):
            await service.verify(binding, other)

        state = empty_state(first, clock)
        state = replace(state, manifest=replace(state.manifest, repository=binding))
        lease_record = TeamLeadLeaseRecord(
            schema_version=1,
            team_id="team-1",
            lease_id="lease-1",
            generation=1,
            holder_session_id="root-1",
            holder_process_id="process-1",
            heartbeat_at=clock.now(),
        )
        attachment = TeamAttachment(state, TeamLeadLease(lease_record), "root-1")
        shutil.move(first, moved)
        with pytest.raises(TeamValidationError):
            await service.verify(binding, moved)
        relinked = await service.relink(attachment, moved)
        assert relinked.workspace_root == moved
        assert relinked.proof_nonce == binding.proof_nonce

    asyncio.run(scenario())
