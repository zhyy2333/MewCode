from __future__ import annotations

import asyncio

import pytest

from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.mailbox import TeamMailboxService
from mewcode.teams.models import (
    MemberWakeReceipt,
    MemberWakeStatus,
    TeamProtocol,
    TeamValidationError,
)
from mewcode.teams.protocols import TeamProtocolRouter
from mewcode.teams.repository import TeamRepository

from .helpers import FakeClock, FakeIds, actor, state_with_members


class WakeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def request_wake(self, member_id: str, *, message_ids) -> MemberWakeReceipt:
        self.calls.append((member_id, tuple(message_ids)))
        return MemberWakeReceipt(member_id, MemberWakeStatus.RUNNING)


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
        assert sent.wake is not None and sent.wake.status is MemberWakeStatus.RUNNING
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


def test_wake_failure_does_not_undo_or_duplicate_persistent_delivery(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, clock=clock))
    leases = TeamLeaseService(repository, now=clock.now, new_id=ids)

    class FailingWake:
        calls = 0

        async def request_wake(self, member_id: str, *, message_ids) -> MemberWakeReceipt:
            self.calls += 1
            return MemberWakeReceipt(member_id, MemberWakeStatus.FAILED, "terminal unavailable")

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        lead = actor(state, fence=lease.fence)
        router = TeamProtocolRouter(repository, state.manifest.name, now=clock.now, new_id=ids)
        wakes = FailingWake()
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
            lead,
            recipient="member-1",
            summary="hello",
            body="persist me",
            protocol=TeamProtocol.TEXT,
            payload={},
            message_id="message-1",
        )
        assert sent.delivered is True
        assert sent.wake is not None and sent.wake.status is MemberWakeStatus.FAILED
        assert "delivered, member not started" in (sent.error or "")
        member = actor(repository.load(state.manifest.name), "member-1", lease.fence)
        assert [item.message_id for item in mailbox.list(member).messages] == ["message-1"]
        repeated = await mailbox.flush_outbox()
        assert repeated.delivered_ids == ()
        assert [item.message_id for item in mailbox.list(member).messages] == ["message-1"]
        assert wakes.calls == 1

    asyncio.run(scenario())


def test_lead_reconciles_unread_delivery_created_by_isolated_member(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(state_with_members(tmp_path, clock=clock))
    leases = TeamLeaseService(repository, now=clock.now, new_id=ids)

    async def scenario() -> None:
        lease = await leases.acquire(state.manifest.name, root_session_id="root-1", process_id="process-1")
        member = actor(state, "member-1", lease.fence)
        router = TeamProtocolRouter(repository, state.manifest.name, now=clock.now, new_id=ids)
        isolated = TeamMailboxService(
            repository,
            state.manifest.name,
            router,
            lease_fence=lambda: lease.fence,
            now=clock.now,
            new_id=ids,
            lock_retry_seconds=0,
        )
        sent = await isolated.send(
            member,
            recipient="member-2",
            summary="handoff",
            body="continue",
            protocol=TeamProtocol.TEXT,
            payload={},
            message_id="member-handoff",
        )
        assert sent.delivered is True and sent.wake is None

        wakes = WakeRecorder()
        lead = TeamMailboxService(
            repository,
            state.manifest.name,
            router,
            lease_fence=lambda: lease.fence,
            wake_sink=wakes,
            now=clock.now,
            new_id=ids,
            lock_retry_seconds=0,
        )
        reconciled = await lead.flush_outbox()
        assert reconciled.wake_receipts["member-handoff"].status is MemberWakeStatus.RUNNING
        assert wakes.calls == [("member-2", ("member-handoff",))]

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
