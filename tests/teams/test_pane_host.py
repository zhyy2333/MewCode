from __future__ import annotations

import asyncio

import pytest

from mewcode.teams.control import (
    ControlCancelRequest,
    ControlRunRequest,
    ControlRunResult,
    ControlShutdownRequest,
    HostRegistration,
    MemberControlBroker,
)
from mewcode.teams.models import TeamMemberOutcomeKind, TeamValidationError
from mewcode.teams.pane_host import ManagedPaneHost, _serve_tcp_host

from .helpers import FakeClock


def test_pane_host_reuses_one_host_for_two_serial_runs() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        broker = MemberControlBroker(now=clock.now, new_id=lambda: "host-1")
        generation = await broker.open("team-1")
        await broker.authorize_pending("member-1", "host-1")
        connection = await broker.register(HostRegistration("team-1", "member-1", "host-1", generation, clock.now()))
        seen: list[str] = []
        async def worker(request: ControlRunRequest) -> ControlRunResult:
            seen.append(request.run_id)
            return ControlRunResult(request.run_id, request.run_generation, TeamMemberOutcomeKind.IDLE.value)
        host = ManagedPaneHost(connection, worker)
        await connection.request_run(ControlRunRequest("run-1", 1, "message"))
        assert (await host.serve_once()).run_id == "run-1"
        await connection.request_run(ControlRunRequest("run-2", 2, "task"))
        assert (await host.serve_once()).run_id == "run-2"
        assert seen == ["run-1", "run-2"]
        await host.close()
    asyncio.run(scenario())


def test_pane_host_rejects_overlap_without_consuming_next_request() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        broker = MemberControlBroker(now=clock.now, new_id=lambda: "host-1")
        generation = await broker.open("team-1")
        await broker.authorize_pending("member-1", "host-1")
        connection = await broker.register(HostRegistration("team-1", "member-1", "host-1", generation, clock.now()))
        started = asyncio.Event()
        release = asyncio.Event()

        async def worker(request: ControlRunRequest) -> ControlRunResult:
            started.set()
            await release.wait()
            return ControlRunResult(request.run_id, request.run_generation, "idle")

        host = ManagedPaneHost(connection, worker)
        await connection.request_run(ControlRunRequest("run-1", 1, "message"))
        first = asyncio.create_task(host.serve_once())
        await started.wait()
        with pytest.raises(TeamValidationError, match="already has"):
            await host.serve_once()
        await connection.request_run(ControlRunRequest("run-2", 2, "message"))
        release.set()
        assert (await first).run_id == "run-1"
        assert (await host.serve_once()).run_id == "run-2"
        await host.close()

    asyncio.run(scenario())


def test_pane_host_close_cancels_active_worker_and_publishes_interrupted() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        broker = MemberControlBroker(now=clock.now, new_id=lambda: "host-1")
        generation = await broker.open("team-1")
        await broker.authorize_pending("member-1", "host-1")
        connection = await broker.register(HostRegistration("team-1", "member-1", "host-1", generation, clock.now()))
        started = asyncio.Event()

        async def worker(request: ControlRunRequest) -> ControlRunResult:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        host = ManagedPaneHost(connection, worker)
        await connection.request_run(ControlRunRequest("run-1", 1, "message"))
        serving = asyncio.create_task(host.serve_once())
        await started.wait()
        await host.close()
        result = await serving
        assert result.outcome == TeamMemberOutcomeKind.INTERRUPTED.value

    asyncio.run(scenario())


def test_tcp_host_consumes_cancel_while_worker_is_running_then_shutdown(tmp_path) -> None:
    async def scenario() -> None:
        class Client:
            def __init__(self) -> None:
                self.requests = asyncio.Queue()
                self.results = []

            async def next_request(self):
                return await self.requests.get()

            async def publish_result(self, result):
                self.results.append(result)

        class Store:
            def write_descriptor(self, descriptor):
                return tmp_path / "member.run.run-1.json"

        client = Client()
        await client.requests.put(ControlRunRequest("run-1", 1, "message"))
        await client.requests.put(ControlCancelRequest("run-1", 1, True))
        await client.requests.put(ControlShutdownRequest())

        async def child_waiter(argv):
            await asyncio.Event().wait()
            return 0

        descriptor = type("Descriptor", (), {"team_id": "team-1", "member_id": "member-1"})()
        assert await _serve_tcp_host(client, descriptor, Store(), child_waiter) is True  # type: ignore[arg-type]
        assert len(client.results) == 1
        assert client.results[0].outcome == TeamMemberOutcomeKind.STOPPED.value

    asyncio.run(scenario())
