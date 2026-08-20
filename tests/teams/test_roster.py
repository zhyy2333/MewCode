from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from mewcode.agent import AgentCapacityPool
from mewcode.permissions import PermissionMode
from mewcode.subagents import (
    AgentDefinition,
    AgentDefinitionCatalog,
    AgentDefinitionLayer,
    AgentDefinitionSource,
)
from mewcode.teams.policy import FrozenRoleFactory
from mewcode.teams.control import ControlRunResult, HostRegistration, MemberControlBroker
from mewcode.teams.mailbox import TeamMailboxService
from mewcode.teams.pane_host import ManagedPaneHost
from mewcode.teams.protocols import TeamProtocolRouter
from mewcode.teams.runtime import TerminalMemberRuntimeFactory
from mewcode.teams.scheduler import TeamMemberScheduler
from mewcode.teams.codec import encode_lead_lease
from mewcode.teams.models import (
    PANE_BINDING_SCHEMA_VERSION,
    PaneHealth,
    MailboxRegistration,
    SCHEMA_VERSION,
    TeamLeadLeaseRecord,
    TeamMemberBackend,
    TeamMemberStatus,
    TeamProtocol,
    TeamValidationError,
    TerminalPaneBinding,
)
from mewcode.teams.repository import TeamProvisioningJournalStore, TeamRepository, atomic_write
from mewcode.teams.roster import TeamRosterService
from mewcode.teams.sessions import MemberSessionStore
from mewcode.worktrees import WorktreeDeleteResult, WorktreeDeleteStatus

from .helpers import FakeClock, actor, empty_state, role, team_name


def test_frozen_role_resolves_profile_and_is_independent_of_source_changes(tmp_path) -> None:
    source_path = tmp_path / "coder.md"
    source_path.write_text("original", encoding="utf-8")
    source = AgentDefinitionSource(
        AgentDefinitionLayer.PROJECT,
        tmp_path,
        source_path,
        "coder.md",
        "project",
    )
    definition = AgentDefinition(
        "coder",
        "Writes code",
        ("read_file", "write_file"),
        ("command",),
        "inherit",
        12,
        PermissionMode.STRICT,
        "Implement the assigned task.",
        source,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    factory = FrozenRoleFactory(
        AgentDefinitionCatalog({"coder": definition}),
        profile_names=("main",),
        now=lambda: now,
        new_id=lambda: "snapshot-1",
    )

    snapshot = factory.build("coder", current_profile_name="main")
    source_path.write_text("changed later", encoding="utf-8")

    assert snapshot.profile_name == "main"
    assert snapshot.snapshot_id == "snapshot-1"
    assert snapshot.system_prompt == "Implement the assigned task."
    assert snapshot.allowed_tool_names == ("read_file", "write_file")
    assert len(snapshot.source_fingerprint) == 64


class _Roles:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock

    def build(self, role_name, *, current_profile_name):
        assert role_name == "coder"
        assert current_profile_name == "main"
        return role(self.clock)


class _Worktrees:
    def __init__(self, root) -> None:
        self.root = root
        self.created = []
        self.deleted = []

    async def create_or_recover(self, name, *, owner):
        self.created.append((name, owner))
        path = self.root / "worktrees" / owner.owner_id
        path.mkdir(parents=True)
        return SimpleNamespace(root=path)

    async def delete(self, name, *, force):
        self.deleted.append((name, force))
        return WorktreeDeleteResult(WorktreeDeleteStatus.DELETED)


class _Resolver:
    def __init__(self, selected=TeamMemberBackend.TMUX) -> None:
        self.selected = selected
        self.requests = []

    def resolve(self, requested):
        self.requests.append(requested)
        return self.selected


class _TerminalHosts:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.provisioned = []
        self.terminated = []

    async def provision(self, team_id, member):
        self.provisioned.append((team_id, member.member_id))
        return TerminalPaneBinding(
            PANE_BINDING_SCHEMA_VERSION,
            member.backend,
            "host-1",
            "%12" if member.backend is TeamMemberBackend.TMUX else None,
            self.clock.now(),
            self.clock.now(),
        )

    async def terminate(self, binding):
        self.terminated.append(binding.host_id)

    def health(self, member_id):
        return PaneHealth.CONNECTED


def _repository(tmp_path, clock: FakeClock):
    repository = TeamRepository(tmp_path, now=clock.now)
    state = repository.create(empty_state(tmp_path, clock))
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
    return repository, state


def test_add_member_success_publishes_only_after_resources_exist(tmp_path) -> None:
    import asyncio

    clock = FakeClock()
    repository, state = _repository(tmp_path, clock)
    worktrees = _Worktrees(tmp_path)
    ids = iter(("member-new", "tx-new"))
    service = TeamRosterService(
        repository,
        team_name(),
        _Roles(clock),
        worktrees,
        MemberSessionStore(repository.paths(team_name()), now=clock.now),
        current_profile_name=lambda: "main",
        now=clock.now,
        new_id=lambda: next(ids),
    )

    member = asyncio.run(
        service.add_member(
            actor(state),
            name="CoderOne",
            role_name="coder",
            backend=TeamMemberBackend.IN_PROCESS,
            requires_approval=True,
        )
    )

    persisted = repository.load(team_name())
    assert member.status is TeamMemberStatus.IDLE
    assert persisted.members[member.member_id] == member
    assert persisted.registry["coderone"].participant_id == member.member_id
    paths = repository.paths(team_name())
    assert paths.member_session_file(member.member_id).exists()
    assert paths.mailbox_file(member.member_id).exists()
    assert not tuple(paths.transactions_root.glob("*.json"))


def test_auto_terminal_member_publishes_binding_view_and_cleans_host(tmp_path) -> None:
    import asyncio

    clock = FakeClock()
    repository, state = _repository(tmp_path, clock)
    worktrees = _Worktrees(tmp_path)
    resolver = _Resolver()
    hosts = _TerminalHosts(clock)
    ids = iter(("member-terminal", "tx-add", "tx-remove"))
    service = TeamRosterService(
        repository,
        team_name(),
        _Roles(clock),
        worktrees,
        MemberSessionStore(repository.paths(team_name()), now=clock.now),
        current_profile_name=lambda: "main",
        backend_resolver=resolver,  # type: ignore[arg-type]
        terminal_hosts=hosts,  # type: ignore[arg-type]
        now=clock.now,
        new_id=lambda: next(ids),
    )
    member = asyncio.run(service.add_member(
        actor(state), name="PaneCoder", role_name="coder", requires_approval=False
    ))
    assert resolver.requests == ["auto"]
    assert member.backend is TeamMemberBackend.TMUX
    assert member.pane_binding is not None and member.pane_binding.host_id == "host-1"
    view = service.list_members(actor(repository.load(team_name())))[0]
    assert view.member == member and view.pane_health is PaneHealth.CONNECTED
    removed = asyncio.run(service.remove_member(actor(repository.load(team_name())), member.member_id))
    assert removed.removed is True
    assert hosts.terminated == ["host-1"]


def test_terminal_provisioning_failure_leaves_no_published_member(tmp_path) -> None:
    import asyncio

    class FailingHosts(_TerminalHosts):
        async def provision(self, team_id, member):
            raise TeamValidationError("pane registration failed")

    clock = FakeClock()
    repository, state = _repository(tmp_path, clock)
    worktrees = _Worktrees(tmp_path)
    ids = iter(("member-terminal", "tx-add"))
    service = TeamRosterService(
        repository,
        team_name(),
        _Roles(clock),
        worktrees,
        MemberSessionStore(repository.paths(team_name()), now=clock.now),
        current_profile_name=lambda: "main",
        backend_resolver=_Resolver(),  # type: ignore[arg-type]
        terminal_hosts=FailingHosts(clock),  # type: ignore[arg-type]
        now=clock.now,
        new_id=lambda: next(ids),
    )
    with pytest.raises(TeamValidationError, match="registration failed"):
        asyncio.run(service.add_member(
            actor(state), name="PaneCoder", role_name="coder", requires_approval=False
        ))
    persisted = repository.load(team_name())
    assert persisted.members == {}
    assert "panecoder" not in persisted.registry
    paths = repository.paths(team_name())
    assert not paths.member_session_file("member-terminal").exists()
    assert not paths.mailbox_file("member-terminal").exists()
    assert not tuple(paths.transactions_root.glob("*.json"))


@pytest.mark.parametrize(
    "backend",
    [TeamMemberBackend.WINDOWS_TERMINAL, TeamMemberBackend.TMUX],
)
def test_terminal_member_end_to_end_reuses_then_replaces_host(tmp_path, backend) -> None:
    import asyncio

    async def scenario() -> None:
        clock = FakeClock()
        repository, state = _repository(tmp_path, clock)
        broker = MemberControlBroker(now=clock.now)
        generation = await broker.open(state.manifest.team_id, control_generation=1)

        class BrokerHosts:
            def __init__(self) -> None:
                self.count = 0
                self.bindings = []
                self.available = True

            async def provision(self, team_id, member):
                assert team_id == state.manifest.team_id
                if not self.available:
                    raise TeamValidationError("terminal backend unavailable")
                self.count += 1
                host_id = f"host-{self.count}"
                await broker.authorize_pending(member.member_id, host_id)
                await broker.register(HostRegistration(
                    team_id, member.member_id, host_id, generation, clock.now()
                ))
                binding = TerminalPaneBinding(
                    PANE_BINDING_SCHEMA_VERSION,
                    member.backend,
                    host_id,
                    f"%{self.count}" if member.backend is TeamMemberBackend.TMUX else None,
                    clock.now(),
                    clock.now(),
                )
                self.bindings.append(binding)
                return binding

            async def terminate(self, binding):
                await broker.disconnect("member-terminal", binding.host_id)

            def health(self, member_id):
                return broker.health(member_id)

        hosts = BrokerHosts()
        ids = iter(("member-terminal", "tx-add", "queue-resume"))
        roster = TeamRosterService(
            repository,
            team_name(),
            _Roles(clock),
            _Worktrees(tmp_path),
            MemberSessionStore(repository.paths(team_name()), now=clock.now),
            current_profile_name=lambda: "main",
            backend_resolver=_Resolver(backend),  # type: ignore[arg-type]
            terminal_hosts=hosts,  # type: ignore[arg-type]
            now=clock.now,
            new_id=lambda: next(ids),
        )
        member = await roster.add_member(
            actor(state), name="PaneCoder", role_name="coder", requires_approval=False
        )
        from mewcode.teams.repository import TeamMutationRunner

        def register_lead(current):
            registry = dict(current.registry)
            registry["lead"] = MailboxRegistration("lead", team_name("lead"), "lead.jsonl", True)
            return replace(current, registry=registry)

        TeamMutationRunner(repository).run(
            team_name(), lease_fence=("lease-1", 1), transform=register_lead
        )

        async def ensure_connection(latest):
            existing = broker.connection(latest.member_id)
            if existing is not None:
                return existing
            binding = await hosts.provision(state.manifest.team_id, latest)

            def publish(current):
                members = dict(current.members)
                members[latest.member_id] = replace(
                    members[latest.member_id], pane_binding=binding
                )
                return replace(current, members=members)

            TeamMutationRunner(repository).run(
                team_name(), lease_fence=("lease-1", 1), transform=publish
            )
            connection = broker.connection(latest.member_id)
            assert connection is not None
            return connection

        scheduler = TeamMemberScheduler(
            repository,
            team_name(),
            AgentCapacityPool(1),
            TerminalMemberRuntimeFactory(broker, ensure_connection=ensure_connection),  # type: ignore[arg-type]
            lease_fence=lambda: ("lease-1", 1),
            now=clock.now,
        )
        mailbox = TeamMailboxService(
            repository,
            team_name(),
            TeamProtocolRouter(repository, team_name(), now=clock.now),
            lease_fence=lambda: ("lease-1", 1),
            wake_sink=scheduler,
            now=clock.now,
            lock_retry_seconds=0,
        )
        roster.set_wake_sink(scheduler)
        seen = []

        async def drive_one(connection, expected):
            async def worker(request):
                seen.append((connection.registration.host_id, request.run_id))
                return ControlRunResult(request.run_id, request.run_generation, "idle", result_summary=expected)

            return await ManagedPaneHost(connection, worker).serve_once()

        async def wait_idle():
            for _ in range(100):
                if repository.load(team_name()).members[member.member_id].status is TeamMemberStatus.IDLE:
                    return
                await asyncio.sleep(0)
            raise AssertionError("terminal member did not become idle")

        lead = actor(repository.load(team_name()))
        first_connection = broker.connection(member.member_id)
        assert first_connection is not None
        first_host = asyncio.create_task(drive_one(first_connection, "round-1"))
        first = await mailbox.send(
            lead, recipient="PaneCoder", summary="one", body="first",
            protocol=TeamProtocol.TEXT,
            payload={}, message_id="mail-1",
        )
        assert first.delivered and first.wake.status.value == "running"
        await first_host
        await wait_idle()

        second_host = asyncio.create_task(drive_one(first_connection, "round-2"))
        await mailbox.send(
            lead, recipient="PaneCoder", summary="two", body="second",
            protocol=TeamProtocol.TEXT,
            payload={}, message_id="mail-2",
        )
        await second_host
        await wait_idle()
        assert [item[0] for item in seen] == ["host-1", "host-1"]

        await broker.disconnect(member.member_id, "host-1")
        hosts.available = False
        third_send = await mailbox.send(
            lead, recipient="PaneCoder", summary="three", body="replacement",
            protocol=TeamProtocol.TEXT,
            payload={}, message_id="mail-3",
        )
        assert third_send.delivered is True
        assert third_send.wake.status.value == "failed"
        assert "delivered, member not started" in (third_send.error or "")
        assert repository.load(team_name()).members[member.member_id].status is TeamMemberStatus.FAILED
        hosts.available = True
        resumed = await roster.resume(
            actor(repository.load(team_name())), member.member_id, reason="terminal restored"
        )
        assert resumed.status is TeamMemberStatus.RUNNING
        replacement = broker.connection(member.member_id)
        assert replacement is not None and replacement.registration.host_id == "host-2"
        third_host = asyncio.create_task(drive_one(replacement, "round-3"))
        await third_host
        await wait_idle()
        persisted = repository.load(team_name()).members[member.member_id]
        assert persisted.member_id == member.member_id
        assert persisted.pane_binding.host_id == "host-2"
        assert [item.message_id for item in mailbox.list(actor(repository.load(team_name()), member.member_id)).messages] == ["mail-1", "mail-2", "mail-3"]
        await scheduler.close()
        await broker.close()

    asyncio.run(scenario())


def test_resume_and_stop_preserve_member_resources(tmp_path) -> None:
    import asyncio

    clock = FakeClock()
    repository, state = _repository(tmp_path, clock)
    worktrees = _Worktrees(tmp_path)
    ids = iter(("member-new", "tx-new", "queue-1"))
    service = TeamRosterService(
        repository,
        team_name(),
        _Roles(clock),
        worktrees,
        MemberSessionStore(repository.paths(team_name()), now=clock.now),
        current_profile_name=lambda: "main",
        now=clock.now,
        new_id=lambda: next(ids),
    )
    member = asyncio.run(
        service.add_member(
            actor(state),
            name="CoderOne",
            role_name="coder",
            backend="in_process",
            requires_approval=False,
        )
    )
    resumed = asyncio.run(service.resume(actor(repository.load(team_name())), member.member_id, reason="continue"))
    assert resumed.status is TeamMemberStatus.QUEUED
    stopped = asyncio.run(service.stop(actor(repository.load(team_name())), member.member_id, reason="pause"))
    assert stopped.status is TeamMemberStatus.STOPPED
    assert repository.paths(team_name()).member_session_file(member.member_id).exists()
    with pytest.raises(TeamValidationError):
        asyncio.run(service.resume(actor(repository.load(team_name())), member.member_id, reason=""))


def test_remove_recovery_keeps_session_and_mailbox_until_worktree_is_safe(tmp_path) -> None:
    import asyncio

    clock = FakeClock()
    repository, _state = _repository(tmp_path, clock)

    class RetainingWorktrees(_Worktrees):
        async def delete(self, name, *, force):
            self.deleted.append((name, force))
            return WorktreeDeleteResult(WorktreeDeleteStatus.RETAINED)

    worktrees = RetainingWorktrees(tmp_path)
    service = TeamRosterService(
        repository,
        team_name(),
        _Roles(clock),
        worktrees,
        MemberSessionStore(repository.paths(team_name()), now=clock.now),
        current_profile_name=lambda: "main",
        now=clock.now,
    )
    paths = repository.paths(team_name())
    paths.ensure_directories()
    paths.member_session_file("removed-member").write_text("session", encoding="utf-8")
    paths.mailbox_file("removed-member").write_text("mail", encoding="utf-8")
    journals = TeamProvisioningJournalStore(repository, team_name())
    journals.write(
        "remove-tx",
        {"operation": "remove_member", "stage": "unpublished", "member_id": "removed-member"},
    )

    assert asyncio.run(service.recover()) == ()
    assert paths.member_session_file("removed-member").exists()
    assert paths.mailbox_file("removed-member").exists()
    assert paths.journal_file("remove-tx").exists()

    worktrees.delete = _Worktrees.delete.__get__(worktrees, RetainingWorktrees)
    assert asyncio.run(service.recover()) == ("remove-tx",)
    assert not paths.member_session_file("removed-member").exists()
    assert not paths.mailbox_file("removed-member").exists()
    assert not paths.journal_file("remove-tx").exists()
