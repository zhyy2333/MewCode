from __future__ import annotations

import asyncio

import pytest

from mewcode.teams.control import (
    CONTROL_SCHEMA_VERSION,
    ControlDescriptorStore,
    ControlRunRequest,
    ControlRunResult,
    HostRegistration,
    MemberControlBroker,
    TcpPaneHostClient,
    _read_message,
)
from mewcode.teams.models import PaneHealth, TeamValidationError
from mewcode.teams.paths import TeamPaths

from .helpers import FakeClock, team_name


def test_broker_authorizes_one_current_generation_host() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        broker = MemberControlBroker(now=clock.now, new_id=lambda: "host-1")
        generation = await broker.open("team-1")
        host = await broker.authorize_pending("member-1")
        connection = await broker.register(HostRegistration("team-1", "member-1", host, generation, clock.now()))
        assert broker.health("member-1") is PaneHealth.CONNECTED
        await connection.publish_result(ControlRunResult("run-1", 1, "idle"))
        assert (await connection.next_result()).outcome == "idle"
        with pytest.raises(TeamValidationError, match="already connected"):
            await broker.register(HostRegistration("team-1", "member-1", host, generation, clock.now()))
        await broker.disconnect("member-1", host)
        assert broker.health("member-1") is PaneHealth.MISSING
    asyncio.run(scenario())


def test_broker_rejects_stale_or_unauthorized_registration() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        broker = MemberControlBroker(now=clock.now, new_id=lambda: "host-1")
        generation = await broker.open("team-1")
        await broker.authorize_pending("member-1", "host-1")
        with pytest.raises(TeamValidationError, match="generation is stale"):
            await broker.register(HostRegistration("team-1", "member-1", "host-1", generation + 1, clock.now()))
        with pytest.raises(TeamValidationError, match="not authorized"):
            await broker.register(HostRegistration("team-1", "member-1", "host-2", generation, clock.now()))
        await broker.close()
        with pytest.raises(TeamValidationError, match="not open"):
            await broker.authorize_pending("member-1")
    asyncio.run(scenario())


def test_broker_uses_lead_control_generation_across_instances() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        broker = MemberControlBroker(now=clock.now)
        assert await broker.open("team-1", control_generation=7) == 7
        await broker.authorize_pending("member-1", "host-1")
        with pytest.raises(TeamValidationError, match="generation is stale"):
            await broker.register(HostRegistration("team-1", "member-1", "host-1", 6, clock.now()))
        connection = await broker.register(HostRegistration("team-1", "member-1", "host-1", 7, clock.now()))
        assert connection.registration.control_generation == 7
        await broker.close()
    asyncio.run(scenario())


def test_loopback_descriptor_registers_and_transfers_one_run(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        paths = TeamPaths.for_user(tmp_path, team_name())
        broker = MemberControlBroker(paths=paths, now=clock.now, new_id=lambda: "host-1", new_token=lambda: "x" * 48)
        await broker.open("team-1")
        await broker.authorize_pending("member-1")
        descriptor = ControlDescriptorStore(paths).read(paths.member_control_file("member-1"))
        assert descriptor.endpoint.host == "127.0.0.1"
        client = TcpPaneHostClient(descriptor)
        await client.open()
        connection = broker.connection("member-1")
        assert connection is not None and broker.health("member-1") is PaneHealth.CONNECTED
        await connection.request_run(ControlRunRequest("run-1", 1, "mail"))
        request = await client.next_request()
        await client.publish_result(ControlRunResult(request.run_id, request.run_generation, "idle"))
        assert (await connection.next_result()).outcome == "idle"
        await client.close()
        await broker.close()
    asyncio.run(scenario())


@pytest.mark.parametrize(
    "message",
    [
        {"schema_version": CONTROL_SCHEMA_VERSION + 1, "type": "heartbeat", "team_id": "team-1", "member_id": "member-1", "host_id": "host-1", "control_generation": 1},
        {"schema_version": CONTROL_SCHEMA_VERSION, "type": "heartbeat", "team_id": "team-1", "member_id": "member-1", "host_id": "host-1", "control_generation": 1, "unknown": True},
        {"schema_version": CONTROL_SCHEMA_VERSION, "type": "run_result", "team_id": "team-1", "member_id": "member-1", "host_id": "host-1", "control_generation": 1, "run_id": "run-1", "run_generation": 1, "outcome": "future"},
    ],
)
def test_protocol_message_rejects_future_unknown_and_invalid_union(message) -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data((__import__("json").dumps(message) + "\n").encode())
        reader.feed_eof()
        with pytest.raises(TeamValidationError):
            await _read_message(reader)
    asyncio.run(scenario())
