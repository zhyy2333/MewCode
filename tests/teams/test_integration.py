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
            now=clock.now,
            new_id=lambda: "team-1",
        )
        attachment = await coordinator.create("Alpha", root_session_id="root-1")
        assert attachment.state.manifest.name.value == "Alpha"
        assert order[:2] == ["flush", "restore"]
        assert coordinator.active_attachment() is not None
        await coordinator.detach()
        assert order[-2:] == ["scheduler.close", "flush"]
        assert coordinator.active_attachment() is None

        await coordinator.attach("Alpha", root_session_id="root-2")
        await coordinator.close()
        assert coordinator.active_attachment() is None
        assert await coordinator.close() == ()

    asyncio.run(scenario())
