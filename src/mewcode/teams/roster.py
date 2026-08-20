from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import uuid

from mewcode.locking import FileLock
from mewcode.worktrees import (
    WorktreeDeleteStatus,
    WorktreeLifecycleService,
    WorktreeNameFactory,
    WorktreeOwner,
    WorktreePurpose,
)

from . import domain
from .models import (
    MAX_MEMBERS,
    MailboxRegistration,
    MemberRemovalResult,
    MemberWakeReason,
    TeamActor,
    TeamActorKind,
    TeamMemberBackend,
    TeamMemberRecord,
    TeamMemberStatus,
    TeamName,
    TeamPermissionError,
    TeamTaskStatus,
    TeamValidationError,
)
from .paths import TeamNamePolicy
from .policy import FrozenRoleFactory
from .repository import TeamMutationRunner, TeamProvisioningJournalStore, TeamRepository
from .sessions import MemberSessionBinding, MemberSessionStore


class TeamRosterService:
    def __init__(
        self,
        repository: TeamRepository,
        team: TeamName,
        roles: FrozenRoleFactory,
        worktrees: WorktreeLifecycleService,
        sessions: MemberSessionStore,
        *,
        current_profile_name: Callable[[], str],
        stop_sink: Callable[[str], Awaitable[None]] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._repository = repository
        self._team = team
        self._roles = roles
        self._worktrees = worktrees
        self._sessions = sessions
        self._current_profile_name = current_profile_name
        self._stop_sink = stop_sink
        self._now = now
        self._new_id = new_id
        self._mutations = TeamMutationRunner(repository)
        self._journals = TeamProvisioningJournalStore(repository, team)
        self._name_policy = TeamNamePolicy()
        self._worktree_names = WorktreeNameFactory()

    async def add_member(
        self,
        actor: TeamActor,
        *,
        name: str,
        role_name: str,
        backend: str | TeamMemberBackend,
        requires_approval: bool,
    ) -> TeamMemberRecord:
        self._require_lead(actor)
        try:
            selected_backend = TeamMemberBackend(backend)
        except ValueError as exc:
            raise TeamValidationError("Unknown team member backend.") from exc
        if selected_backend is not TeamMemberBackend.IN_PROCESS:
            raise TeamValidationError("This phase only supports the in_process member backend.")
        member_name = self._name_policy.parse(name)
        initial = self._repository.load(self._team)
        self._validate_new_member(initial, member_name)
        role = self._roles.build(
            role_name,
            current_profile_name=self._current_profile_name(),
        )
        member_id = self._new_id()
        transaction_id = self._new_id()
        worktree_name = self._worktree_names.for_team_member(
            initial.manifest.team_id,
            member_id,
        )
        owner = WorktreeOwner(WorktreePurpose.TEAM_MEMBER, member_id, True)
        self._journals.write(
            transaction_id,
            {
                "operation": "add_member",
                "stage": "intent",
                "member_id": member_id,
                "member_name": member_name.value,
                "worktree_name": worktree_name.value,
            },
        )
        session: MemberSessionBinding | None = None
        worktree_created = False
        published = False
        try:
            environment = await self._worktrees.create_or_recover(
                worktree_name,
                owner=owner,
            )
            worktree_created = True
            current = self._now()
            member = TeamMemberRecord(
                member_id,
                member_name,
                role,
                selected_backend,
                requires_approval,
                TeamMemberStatus.IDLE,
                worktree_name.value,
                environment.root,
                member_id,
                f"{member_id}.jsonl",
                f"{member_id}.jsonl",
                None,
                None,
                0,
                None,
                current,
                current,
            )
            session = self._sessions.create(member)
            mailbox = self._repository.paths(self._team).mailbox_file(member_id)
            mailbox.parent.mkdir(parents=True, exist_ok=True)
            with mailbox.open("xb"):
                pass

            def publish(state):
                self._validate_new_member(state, member_name)
                members = dict(state.members)
                members[member_id] = member
                registry = dict(state.registry)
                registry[member_name.canonical_key] = MailboxRegistration(
                    member_id,
                    member_name,
                    member.mailbox_name,
                    False,
                )
                return replace(
                    state,
                    members=members,
                    registry=registry,
                    updated_at=self._now(),
                )

            committed = self._mutations.run(
                self._team,
                lease_fence=actor.lease_fence,
                transform=publish,
            )
            published = True
            self._journals.delete(transaction_id)
            return committed.members[member_id]
        except BaseException:
            if not published:
                rolled_back = await self._rollback_member_resources(
                    member_id,
                    worktree_name,
                    session,
                    worktree_created,
                )
                if rolled_back:
                    self._journals.delete(transaction_id)
            raise
        finally:
            if session is not None:
                session.close()

    def list_members(self, actor: TeamActor) -> tuple[TeamMemberRecord, ...]:
        state = self._repository.load(self._team)
        self._require_participant(actor, state.manifest.team_id)
        return tuple(sorted(state.members.values(), key=lambda item: item.name.canonical_key))

    async def refresh_role(
        self,
        actor: TeamActor,
        member_id: str,
        *,
        role_name: str,
    ) -> TeamMemberRecord:
        self._require_lead(actor)
        snapshot = self._roles.build(
            role_name,
            current_profile_name=self._current_profile_name(),
        )

        def transform(state):
            member = self._member(state, member_id)
            if member.status not in {TeamMemberStatus.IDLE, TeamMemberStatus.STOPPED}:
                raise TeamValidationError("Only idle or stopped members may refresh roles.")
            members = dict(state.members)
            members[member_id] = replace(member, role=snapshot, updated_at=self._now())
            return replace(state, members=members, updated_at=self._now())

        committed = self._mutations.run(
            self._team,
            lease_fence=actor.lease_fence,
            transform=transform,
        )
        return committed.members[member_id]

    async def resume(
        self,
        actor: TeamActor,
        member_id: str,
        *,
        reason: str,
    ) -> TeamMemberRecord:
        self._require_lead(actor)
        if not isinstance(reason, str) or not reason.strip():
            raise TeamValidationError("Member resume requires a non-empty reason.")
        queue_id = self._new_id()

        def transform(state):
            member = self._member(state, member_id)
            allowed = {
                TeamMemberStatus.IDLE,
                TeamMemberStatus.INTERRUPTED,
                TeamMemberStatus.FAILED,
                TeamMemberStatus.STOPPED,
            }
            if member.status not in allowed:
                raise TeamValidationError("Member cannot be resumed from its current state.")
            if member.status is TeamMemberStatus.STOPPED:
                state = domain.transition_member(state, member_id, TeamMemberStatus.QUEUED, now=self._now())
            state, _entry = domain.enqueue_member(
                state,
                member_id,
                queue_id=queue_id,
                reason=MemberWakeReason.EXPLICIT_RESUME,
                message_ids=(),
                now=self._now(),
            )
            return state

        committed = self._mutations.run(
            self._team,
            lease_fence=actor.lease_fence,
            transform=transform,
        )
        return committed.members[member_id]

    async def stop(
        self,
        actor: TeamActor,
        member_id: str,
        *,
        reason: str,
    ) -> TeamMemberRecord:
        self._require_lead(actor)
        if not isinstance(reason, str) or not reason.strip():
            raise TeamValidationError("Member stop requires a non-empty reason.")
        was_active = False

        def transform(state):
            nonlocal was_active
            member = self._member(state, member_id)
            was_active = member.status is TeamMemberStatus.RUNNING
            if member.status is TeamMemberStatus.STOPPED:
                return state
            candidate = domain.dequeue_member(state, member_id, now=self._now())
            return domain.transition_member(
                candidate,
                member_id,
                TeamMemberStatus.STOPPED,
                now=self._now(),
                error=reason,
            )

        committed = self._mutations.run(
            self._team,
            lease_fence=actor.lease_fence,
            transform=transform,
        )
        if was_active and self._stop_sink is not None:
            await self._stop_sink(member_id)
        return committed.members[member_id]

    async def remove_member(
        self,
        actor: TeamActor,
        member_id: str,
    ) -> MemberRemovalResult:
        self._require_lead(actor)
        state = self._repository.load(self._team)
        member = self._member(state, member_id)
        if member.status not in {
            TeamMemberStatus.IDLE,
            TeamMemberStatus.STOPPED,
            TeamMemberStatus.INTERRUPTED,
            TeamMemberStatus.FAILED,
        }:
            raise TeamValidationError("Active or approval-waiting members cannot be removed.")
        if any(
            task.assignee_id == member_id and not task.status.terminal
            for task in state.tasks.values()
        ):
            raise TeamValidationError("Member still owns a non-terminal task.")
        member_lock = FileLock(self._repository.paths(self._team).member_recovery_lock(member_id))
        if not member_lock.acquire():
            raise TeamValidationError("Member is being resumed in another process.")
        transaction_id = self._new_id()
        self._journals.write(
            transaction_id,
            {"operation": "remove_member", "stage": "intent", "member_id": member_id},
        )
        try:
            def deregister(current):
                existing = self._member(current, member_id)
                if existing.run_generation != member.run_generation:
                    raise TeamValidationError("Member changed while removal was starting.")
                members = dict(current.members)
                del members[member_id]
                registry = {
                    key: value
                    for key, value in current.registry.items()
                    if value.participant_id != member_id
                }
                queue = tuple(item for item in current.queue if item.member_id != member_id)
                return replace(
                    current,
                    members=members,
                    registry=registry,
                    queue=queue,
                    updated_at=self._now(),
                )

            self._mutations.run(
                self._team,
                lease_fence=actor.lease_fence,
                transform=deregister,
            )
            name = self._worktree_names.for_team_member(state.manifest.team_id, member_id)
            deleted = await self._worktrees.delete(name, force=False)
            if deleted.status not in {
                WorktreeDeleteStatus.DELETED,
                WorktreeDeleteStatus.ALREADY_ABSENT,
            }:
                return MemberRemovalResult(
                    True,
                    member.worktree_root,
                    deleted.reason or "Worktree contains retained work.",
                )
            paths = self._repository.paths(self._team)
            paths.member_session_file(member_id).unlink(missing_ok=True)
            paths.mailbox_file(member_id).unlink(missing_ok=True)
            self._journals.delete(transaction_id)
            return MemberRemovalResult(True)
        finally:
            member_lock.close()

    async def recover(self) -> tuple[str, ...]:
        """Idempotently settle member provisioning journals after a crash."""
        recovered: list[str] = []
        for transaction_id, payload in self._journals.list():
            operation = payload.get("operation")
            member_id = payload.get("member_id")
            if not isinstance(member_id, str):
                continue
            state = self._repository.load(self._team)
            if operation == "add_member" and member_id in state.members:
                self._journals.delete(transaction_id)
                recovered.append(transaction_id)
                continue
            if operation not in {"add_member", "remove_member"}:
                continue
            name = self._worktree_names.for_team_member(state.manifest.team_id, member_id)
            if operation == "remove_member":
                result = await self._worktrees.delete(name, force=False)
                if result.status not in {
                    WorktreeDeleteStatus.DELETED,
                    WorktreeDeleteStatus.ALREADY_ABSENT,
                }:
                    continue
                paths = self._repository.paths(self._team)
                paths.member_session_file(member_id).unlink(missing_ok=True)
                paths.mailbox_file(member_id).unlink(missing_ok=True)
                self._journals.delete(transaction_id)
                recovered.append(transaction_id)
                continue
            rolled_back = await self._rollback_member_resources(
                member_id,
                name,
                None,
                True,
            )
            if rolled_back:
                self._journals.delete(transaction_id)
                recovered.append(transaction_id)
        return tuple(recovered)

    async def _rollback_member_resources(
        self,
        member_id: str,
        worktree_name,
        session: MemberSessionBinding | None,
        worktree_created: bool,
    ) -> bool:
        if session is not None:
            session.close()
        paths = self._repository.paths(self._team)
        paths.member_session_file(member_id).unlink(missing_ok=True)
        paths.mailbox_file(member_id).unlink(missing_ok=True)
        if worktree_created:
            result = await self._worktrees.delete(worktree_name, force=False)
            return result.status in {
                WorktreeDeleteStatus.DELETED,
                WorktreeDeleteStatus.ALREADY_ABSENT,
            }
        return True

    @staticmethod
    def _member(state, member_id: str) -> TeamMemberRecord:
        try:
            return state.members[member_id]
        except KeyError as exc:
            raise TeamValidationError("Unknown team member.") from exc

    @staticmethod
    def _require_participant(actor: TeamActor, team_id: str) -> None:
        if actor.team_id != team_id:
            raise TeamPermissionError("Actor belongs to another team.")

    @staticmethod
    def _require_lead(actor: TeamActor) -> None:
        if actor.kind is not TeamActorKind.LEAD:
            raise TeamPermissionError("Only the Team Lead may manage the roster.")

    @staticmethod
    def _validate_new_member(state, name) -> None:
        if len(state.members) >= MAX_MEMBERS:
            raise TeamValidationError("Team member limit has been reached.")
        if name.canonical_key in state.registry:
            raise TeamValidationError("Team member name is already registered.")
