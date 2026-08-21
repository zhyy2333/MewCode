from __future__ import annotations

import asyncio
from dataclasses import replace

from mewcode.teams.coordinator import TeamCoordinator, TeamCoordinatorServices
from mewcode.teams.leases import TeamLeaseService
from mewcode.teams.repository import TeamRepository

from .helpers import FakeClock, binding


class _Bindings:
    def __init__(self, root, clock) -> None:
        self.root = root
        self.clock = clock
        self.verified = 0

    async def create_binding(self, team_id, workspace):
        assert workspace == self.root
        return replace(binding(self.root, self.clock), repository_marker_id=f"marker-{team_id}")

    async def verify(self, value, workspace):
        assert value.workspace_root == workspace
        self.verified += 1

    async def relink(self, attachment, workspace):
        return replace(
            attachment.state.manifest.repository,
            workspace_root=workspace,
            common_dir=workspace / ".git",
            relinked_at=self.clock.now(),
        )


class _Scheduler:
    def __init__(self, order) -> None:
        self.order = order

    async def restore(self):
        self.order.append("restore")

    async def close(self):
        self.order.append("scheduler.close")


class _Mailbox:
    def __init__(self, order) -> None:
        self.order = order

    async def flush_outbox(self):
        self.order.append("flush")


class _Delivery:
    def __init__(self, order) -> None:
        self.order = order

    async def open(self):
        self.order.append("delivery.open")

    async def close(self):
        self.order.append("delivery.close")


class _Broker:
    def __init__(self, order) -> None:
        self.order = order

    async def open(self, team_id, *, control_generation):
        self.order.append(f"broker.open:{team_id}:{control_generation}")

    async def close(self):
        self.order.append("broker.close")


def test_create_attach_detach_and_close_order(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        repository = TeamRepository(tmp_path, now=clock.now)
        lease_ids = iter(("lease-1", "lease-2"))
        leases = TeamLeaseService(
            repository,
            now=clock.now,
            new_id=lambda: next(lease_ids),
        )
        order = []

        def services(team, fence):
            assert fence()[0].startswith("lease-")
            return TeamCoordinatorServices(
                scheduler=_Scheduler(order),
                mailbox=_Mailbox(order),
            )

        coordinator = TeamCoordinator(
            repository,
            leases,
            _Bindings(tmp_path, clock),
            tmp_path,
            process_id="process-1",
            services_factory=services,
            control_broker=_Broker(order),  # type: ignore[arg-type]
            now=clock.now,
            new_id=lambda: "team-1",
        )
        attachment = await coordinator.create("Alpha", root_session_id="root-1")
        assert attachment.state.manifest.name.value == "Alpha"
        assert order[:3] == ["broker.open:team-1:1", "flush", "restore"]
        assert coordinator.active_attachment() is not None
        await coordinator.detach()
        assert order[-3:] == ["scheduler.close", "broker.close", "flush"]
        assert coordinator.active_attachment() is None

        await coordinator.attach("Alpha", root_session_id="root-2")
        await coordinator.close()
        assert coordinator.active_attachment() is None
        assert await coordinator.close() == ()

    asyncio.run(scenario())


def test_enabled_delivery_opens_before_wake_restore_and_closes_first(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        repository = TeamRepository(tmp_path, now=clock.now)
        leases = TeamLeaseService(repository, now=clock.now, new_id=lambda: "lease-1")
        order = []

        def services(team, fence):
            del team, fence
            return TeamCoordinatorServices(
                scheduler=_Scheduler(order),
                mailbox=_Mailbox(order),
                delivery=_Delivery(order),
            )

        coordinator = TeamCoordinator(
            repository,
            leases,
            _Bindings(tmp_path, clock),
            tmp_path,
            process_id="process-1",
            services_factory=services,
            control_broker=_Broker(order),  # type: ignore[arg-type]
            now=clock.now,
            new_id=lambda: "team-1",
        )
        await coordinator.create("Alpha", root_session_id="root-1")
        assert order == ["broker.open:team-1:1", "delivery.open", "flush", "restore"]
        await coordinator.close()
        assert order[-4:] == ["delivery.close", "scheduler.close", "broker.close", "flush"]

    asyncio.run(scenario())
