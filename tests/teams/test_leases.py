from __future__ import annotations

import asyncio

import pytest

from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.models import TeamLeaseError
from mewcode.teams.repository import TeamRepository

from .helpers import FakeClock, FakeIds, empty_state, team_name


def test_lease_is_exclusive_renews_and_expires(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    repository = TeamRepository(tmp_path, now=clock.now)
    repository.create(empty_state(tmp_path, clock))
    service = TeamLeaseService(repository, now=clock.now, new_id=ids)

    async def scenario() -> None:
        first = await service.acquire(team_name(), root_session_id="root-1", process_id="process-1")
        with pytest.raises(TeamLeaseError):
            await service.acquire(team_name(), root_session_id="root-2", process_id="process-2")
        clock.advance(10)
        renewed = await service.renew(first)
        assert renewed.record.heartbeat_at == clock.now()
        clock.advance(60)
        with pytest.raises(TeamLeaseError):
            await service.validate(renewed)
        second = await service.acquire(team_name(), root_session_id="root-2", process_id="process-2")
        assert second.record.generation == 2
        with pytest.raises(TeamLeaseError):
            await service.renew(first)
        await service.release(second)
        third = await service.acquire(team_name(), root_session_id="root-3", process_id="process-3")
        assert third.record.generation == 3

    asyncio.run(scenario())
