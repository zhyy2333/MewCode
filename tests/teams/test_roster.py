from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from mewcode.permissions import PermissionMode
from mewcode.subagents import (
    AgentDefinition,
    AgentDefinitionCatalog,
    AgentDefinitionLayer,
    AgentDefinitionSource,
)
from mewcode.teams.policy import FrozenRoleFactory
from mewcode.teams.codec import encode_lead_lease
from mewcode.teams.models import (
    SCHEMA_VERSION,
    TeamLeadLeaseRecord,
    TeamMemberBackend,
    TeamMemberStatus,
    TeamValidationError,
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
