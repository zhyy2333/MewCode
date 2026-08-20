from __future__ import annotations

import asyncio
from dataclasses import replace

from mewcode.agent import AgentCapacityPool
from mewcode.teams.codec import encode_lead_lease
from mewcode.teams.models import (
    MemberWakeStatus,
    SCHEMA_VERSION,
    TeamLeadLeaseRecord,
    TeamMemberOutcome,
    TeamMemberOutcomeKind,
    TeamMemberStatus,
)
from mewcode.teams.repository import TeamRepository, atomic_write
from mewcode.teams.scheduler import TeamMemberScheduler

from .helpers import FakeClock, state_with_members, team_name


class _Runtime:
    def __init__(self, lease, outcome=None) -> None:
        self.lease = lease
        self._outcome = outcome or TeamMemberOutcome(TeamMemberOutcomeKind.IDLE, "done")
        self.cancelled = False

    async def events(self):
        if False:
            yield None

    @property
    def outcome(self):
        return self._outcome

    async def cancel(self, *, explicit_stop=False):
        self.cancelled = True
        self._outcome = TeamMemberOutcome(
            TeamMemberOutcomeKind.STOPPED if explicit_stop else TeamMemberOutcomeKind.INTERRUPTED
        )

    async def close(self):
        await self.lease.close()


class _RuntimeFactory:
    def __init__(self) -> None:
        self.created = []

    async def create(self, state, member_id, capacity_lease, *, reason):
        self.created.append((state.members[member_id].run_generation, reason))
        return _Runtime(capacity_lease)


class _FailingRuntimeFactory:
    async def create(self, state, member_id, capacity_lease, *, reason):
        await capacity_lease.close()
        raise RuntimeError("terminal secret must not escape")


def _repository(tmp_path, clock):
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, 1, clock))
    lease = TeamLeadLeaseRecord(
        SCHEMA_VERSION,
        state.manifest.team_id,
        "lease-1",
        1,
        "session-1",
        "process-1",
        clock.now(),
    )
    atomic_write(repository.paths(team_name()).lease_file, encode_lead_lease(lease))
    return repository


async def _settle_status(repository, expected):
    for _ in range(100):
        if repository.load(team_name()).members["member-1"].status is expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"member did not reach {expected}")


def test_wake_coalesces_while_capacity_waits_then_runs_once(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        repository = _repository(tmp_path, clock)
        pool = AgentCapacityPool(1)
        blocker = await pool.acquire("subagent", "busy")
        factory = _RuntimeFactory()
        ids = (f"id-{index}" for index in range(20))
        scheduler = TeamMemberScheduler(
            repository,
            team_name(),
            pool,
            factory,
            lease_fence=lambda: ("lease-1", 1),
            now=clock.now,
            new_id=lambda: next(ids),
        )
        first = await scheduler.request_wake("member-1", message_ids=("mail-1",))
        second = await scheduler.request_wake("member-1", message_ids=("mail-2",))
        assert first.status is MemberWakeStatus.QUEUED
        assert second.status is MemberWakeStatus.QUEUED
        queued = repository.load(team_name())
        assert len(queued.queue) == 1
        assert queued.queue[0].message_ids == ("mail-1", "mail-2")
        await blocker.close()
        await _settle_status(repository, TeamMemberStatus.IDLE)
        assert factory.created == [(1, "persistent wake queue")]
        assert repository.load(team_name()).members["member-1"].current_task_id is None
        await scheduler.close()
        assert pool.active_count == 0

    asyncio.run(scenario())


def test_startup_failure_returns_failed_receipt_and_converges_member(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        repository = _repository(tmp_path, clock)
        scheduler = TeamMemberScheduler(
            repository,
            team_name(),
            AgentCapacityPool(1),
            _FailingRuntimeFactory(),  # type: ignore[arg-type]
            lease_fence=lambda: ("lease-1", 1),
            now=clock.now,
            new_id=lambda: "run-1",
        )
        receipt = await scheduler.request_wake("member-1", message_ids=("mail-1",))
        assert receipt.status is MemberWakeStatus.FAILED
        assert "RuntimeError" in (receipt.diagnostic or "")
        assert "secret" not in (receipt.diagnostic or "")
        assert repository.load(team_name()).members["member-1"].status is TeamMemberStatus.FAILED
        await scheduler.close()

    asyncio.run(scenario())


def test_restore_only_starts_persisted_queue_not_interrupted_member(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        repository = _repository(tmp_path, clock)
        state = repository.load(team_name())
        member = replace(state.members["member-1"], status=TeamMemberStatus.INTERRUPTED)
        repository.compare_and_swap(
            team_name(),
            expected_revision=state.revision,
            lease_fence=("lease-1", 1),
            candidate=replace(state, members={"member-1": member}),
        )
        factory = _RuntimeFactory()
        scheduler = TeamMemberScheduler(
            repository,
            team_name(),
            AgentCapacityPool(1),
            factory,
            lease_fence=lambda: ("lease-1", 1),
        )
        assert await scheduler.restore() == ()
        assert factory.created == []
        await scheduler.close()

    asyncio.run(scenario())
