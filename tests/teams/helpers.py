from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

from mewcode.permissions import PermissionMode, PermissionRuleSets
from mewcode.teams.models import (
    FrozenRoleSnapshot,
    MailboxRegistration,
    RepositoryBinding,
    TeamManifest,
    TeamActor,
    TeamActorKind,
    TeamMemberBackend,
    TeamMemberRecord,
    TeamMemberStatus,
    TeamName,
    TeamState,
)


class FakeClock:
    def __init__(self, value: datetime | None = None) -> None:
        self.value = value or datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class FakeIds:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self) -> str:
        self._next += 1
        return f"id-{self._next}"


def team_name(value: str = "alpha") -> TeamName:
    return TeamName(value=value, canonical_key=value.casefold())


def binding(root: Path, clock: FakeClock | None = None) -> RepositoryBinding:
    current = (clock or FakeClock()).now()
    return RepositoryBinding(
        repository_marker_id="marker-1",
        repository_id="repository-1",
        workspace_root=root,
        common_dir=root / ".git",
        proof_nonce="proof-1",
        created_at=current,
    )


def role(clock: FakeClock | None = None) -> FrozenRoleSnapshot:
    current = (clock or FakeClock()).now()
    return FrozenRoleSnapshot(
        snapshot_id="role-1",
        role_name="coder",
        source_fingerprint="fingerprint-1",
        description="Writes code",
        system_prompt="Implement the task.",
        profile_name="default",
        max_turns=20,
        permission_mode=PermissionMode.DEFAULT,
        allowed_tool_names=("read_file", "write_file"),
        denied_tool_names=(),
        permission_rules=PermissionRuleSets(),
        created_at=current,
    )


def empty_state(root: Path, clock: FakeClock | None = None) -> TeamState:
    timer = clock or FakeClock()
    current = timer.now()
    return TeamState(
        schema_version=1,
        revision=0,
        manifest=TeamManifest(
            team_id="team-1",
            name=team_name(),
            leader_name="lead",
            repository=binding(root, timer),
            created_at=current,
            updated_at=current,
        ),
        members={},
        registry={},
        tasks={},
        approvals={},
        queue=(),
        outbox=(),
        updated_at=current,
    )


def state_with_members(root: Path, count: int = 2, clock: FakeClock | None = None) -> TeamState:
    timer = clock or FakeClock()
    state = empty_state(root, timer)
    lead_name = team_name("lead")
    registry = {
        lead_name.canonical_key: MailboxRegistration("lead", lead_name, "lead.jsonl", True)
    }
    members = {}
    for index in range(1, count + 1):
        member_id = f"member-{index}"
        name = team_name(member_id)
        member = TeamMemberRecord(
            member_id=member_id,
            name=name,
            role=role(timer),
            backend=TeamMemberBackend.IN_PROCESS,
            requires_approval=False,
            status=TeamMemberStatus.IDLE,
            worktree_name=f"team/a/{member_id}",
            worktree_root=root / member_id,
            worktree_owner_id=member_id,
            mailbox_name=f"{member_id}.jsonl",
            session_name=f"{member_id}.jsonl",
            current_task_id=None,
            active_run_id=None,
            run_generation=0,
            last_error=None,
            created_at=timer.now(),
            updated_at=timer.now(),
        )
        members[member_id] = member
        registry[name.canonical_key] = MailboxRegistration(member_id, name, member.mailbox_name, False)
    return replace(state, members=members, registry=registry)


def actor(state: TeamState, member_id: str | None = None, fence: tuple[str, int] = ("lease-1", 1)) -> TeamActor:
    if member_id is None:
        return TeamActor("lead", team_name("lead"), TeamActorKind.LEAD, state.manifest.team_id, fence)
    return TeamActor(member_id, state.members[member_id].name, TeamActorKind.MEMBER, state.manifest.team_id, fence)
