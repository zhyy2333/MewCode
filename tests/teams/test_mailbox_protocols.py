from __future__ import annotations

import asyncio

import pytest

from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.mailbox import TeamMailboxService
from mewcode.teams.models import TeamProtocol, TeamValidationError
from mewcode.teams.protocols import TeamProtocolRouter
from mewcode.teams.repository import TeamRepository

from .helpers import FakeClock, FakeIds, actor, state_with_members


class WakeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def request_wake(self, member_id: str, *, message_ids) -> None:
        self.calls.append((member_id, tuple(message_ids)))


def test_mailbox_send_read_broadcast_and_wake(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, clock=clock))
    leases = TeamLeaseService(repository, now=clock.now, new_id=ids)

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        lead = actor(state, fence=lease.fence)
        router = TeamProtocolRouter(repository, state.manifest.name, now=clock.now, new_id=ids)
        wakes = WakeRecorder()
        mailbox = TeamMailboxService(
            repository,
            state.manifest.name,
            router,
            lease_fence=lambda: lease.fence,
            wake_sink=wakes,
            now=clock.now,
            new_id=ids,
            lock_retry_seconds=0,
        )
        sent = await mailbox.send(
            lead, recipient="member-1", summary="hello", body="world",
            protocol=TeamProtocol.TEXT, payload={},
        )
        assert sent.delivered is True
        member = actor(repository.load(state.manifest.name), "member-1", lease.fence)
        page = mailbox.list(member)
        assert [item.body for item in page.messages] == ["world"]
        assert await mailbox.mark_read(member, (sent.message_id,)) == (sent.message_id,)
        assert mailbox.list(member).messages == ()
        broadcast = await mailbox.broadcast(
            lead, summary="all", body="notice", protocol=TeamProtocol.TEXT, payload={},
        )
        assert len(broadcast.results) == 2
        assert all(item.delivered for item in broadcast.results)
        assert wakes and wakes.calls[0][0] == "member-1"

    asyncio.run(scenario())


def test_protocol_rejects_unknown_direction_and_fields(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, clock=clock))
    leases = TeamLeaseService(repository, now=clock.now, new_id=ids)

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        member = actor(state, "member-1", lease.fence)
        router = TeamProtocolRouter(repository, state.manifest.name, now=clock.now, new_id=ids)
        mailbox = TeamMailboxService(
            repository, state.manifest.name, router,
            lease_fence=lambda: lease.fence, now=clock.now, new_id=ids, lock_retry_seconds=0,
        )
        with pytest.raises(TeamValidationError):
            await mailbox.send(
                member, recipient="member-2", summary="stop", body="stop",
                protocol=TeamProtocol.STOP_REQUEST,
                payload={"member_id": "member-2", "reason": "test"},
            )
        with pytest.raises(TeamValidationError):
            await mailbox.send(
                member, recipient="lead", summary="status", body="done",
                protocol=TeamProtocol.TASK_STATUS,
                payload={"task_id": "x", "task_revision": 0, "status": "completed", "extra": True},
            )

    asyncio.run(scenario())
