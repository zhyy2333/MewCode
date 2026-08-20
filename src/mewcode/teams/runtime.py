from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
import inspect

from mewcode.agent import AgentContextStatus, AgentProgress, AgentRun, StopReason
from mewcode.agent.capacity import AgentCapacityLease
from mewcode.providers import ChatMessage
from mewcode.worktrees import (
    WorktreeLease,
    WorktreeLifecycleService,
    WorktreeNameFactory,
    WorktreeOwner,
    WorktreePurpose,
)

from .domain import approval_is_valid
from .models import (
    TeamMemberOutcome,
    TeamMemberOutcomeKind,
    TeamMemberProgress,
    TeamMemberRecord,
    TeamMemberStatus,
    TeamState,
    TeamValidationError,
)
from .sessions import MemberSessionBinding, MemberSessionStore


@dataclass(frozen=True)
class TeamRuntimeBuildContext:
    state: TeamState
    member: TeamMemberRecord
    worktree_lease: WorktreeLease
    session: MemberSessionBinding
    history: tuple[ChatMessage, ...]
    resume_prompt: str


@dataclass
class TeamMemberRunBundle:
    run: AgentRun
    close_callback: Callable[[], Awaitable[None] | None] = lambda: None
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        result = self.close_callback()
        if inspect.isawaitable(result):
            await result


MemberRunBuilder = Callable[
    [TeamRuntimeBuildContext],
    TeamMemberRunBundle | Awaitable[TeamMemberRunBundle],
]


class TeamMemberRuntimeFactory:
    def __init__(
        self,
        worktrees: WorktreeLifecycleService,
        sessions: MemberSessionStore,
        build_run: MemberRunBuilder,
    ) -> None:
        self._worktrees = worktrees
        self._sessions = sessions
        self._build_run = build_run
        self._names = WorktreeNameFactory()

    async def create(
        self,
        state: TeamState,
        member_id: str,
        capacity_lease: AgentCapacityLease,
        *,
        reason: str,
    ) -> TeamMemberRuntime:
        try:
            member = state.members[member_id]
        except KeyError as exc:
            await capacity_lease.close()
            raise TeamValidationError("Unknown team member runtime identity.") from exc
        if member.status is not TeamMemberStatus.RUNNING or member.active_run_id is None:
            await capacity_lease.close()
            raise TeamValidationError("Member runtime requires a committed RUNNING state.")
        if capacity_lease.owner_id != member_id:
            await capacity_lease.close()
            raise TeamValidationError("Capacity lease belongs to another member.")
        expected_name = self._names.for_team_member(state.manifest.team_id, member_id)
        if expected_name.value != member.worktree_name:
            await capacity_lease.close()
            raise TeamValidationError("Member Worktree identity is inconsistent.")
        owner = WorktreeOwner(WorktreePurpose.TEAM_MEMBER, member_id, True)
        worktree_lease: WorktreeLease | None = None
        session: MemberSessionBinding | None = None
        bundle: TeamMemberRunBundle | None = None
        try:
            environment = await self._worktrees.create_or_recover(expected_name, owner=owner)
            if environment.root != member.worktree_root:
                raise TeamValidationError("Recovered member Worktree path changed.")
            worktree_lease = await self._worktrees.enter(environment, owner=owner)
            session, session_state = self._sessions.open(member)
            context = TeamRuntimeBuildContext(
                state,
                member,
                worktree_lease,
                session,
                session_state.messages,
                _resume_prompt(state, member, reason),
            )
            created = self._build_run(context)
            bundle = await created if inspect.isawaitable(created) else created
            return TeamMemberRuntime(
                member,
                bundle,
                session,
                worktree_lease,
                capacity_lease,
                self._worktrees,
            )
        except BaseException:
            if bundle is not None:
                await bundle.close()
            if session is not None:
                session.close()
            if worktree_lease is not None:
                await self._worktrees.suspend(worktree_lease)
            await capacity_lease.close()
            raise


class TeamMemberRuntime:
    def __init__(
        self,
        member: TeamMemberRecord,
        bundle: TeamMemberRunBundle,
        session: MemberSessionBinding,
        worktree_lease: WorktreeLease,
        capacity_lease: AgentCapacityLease,
        worktrees: WorktreeLifecycleService,
    ) -> None:
        self.member = member
        self._bundle = bundle
        self._session = session
        self._worktree_lease = worktree_lease
        self._capacity_lease = capacity_lease
        self._worktrees = worktrees
        self._outcome: TeamMemberOutcome | None = None
        self._explicit_stop = False
        self._closed = False

    async def events(self) -> AsyncIterator[TeamMemberProgress]:
        try:
            async for event in self._bundle.run.events():
                if isinstance(event, AgentProgress):
                    yield TeamMemberProgress(event.phase, event.message)
                elif isinstance(event, AgentContextStatus):
                    yield TeamMemberProgress("context", event.status.message)
            outcome = self._bundle.run.outcome
            self._outcome = _map_outcome(outcome.reason, outcome.final_text, outcome.error, self._explicit_stop)
        except BaseException as exc:
            if self._outcome is None:
                self._outcome = TeamMemberOutcome(
                    TeamMemberOutcomeKind.INTERRUPTED
                    if isinstance(exc, (GeneratorExit, KeyboardInterrupt))
                    else TeamMemberOutcomeKind.FAILED,
                    error=f"Member runtime failed: {type(exc).__name__}.",
                )
            raise

    @property
    def outcome(self) -> TeamMemberOutcome:
        if self._outcome is None:
            raise RuntimeError("Team member runtime has not reached an outcome.")
        return self._outcome

    async def cancel(self, *, explicit_stop: bool = False) -> None:
        self._explicit_stop = self._explicit_stop or explicit_stop
        await self._bundle.run.cancel()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        try:
            await self._bundle.close()
        except BaseException as exc:
            first_error = exc
        try:
            self._session.close()
        except BaseException as exc:
            first_error = first_error or exc
        try:
            await self._worktrees.suspend(self._worktree_lease)
        except BaseException as exc:
            first_error = first_error or exc
        finally:
            await self._capacity_lease.close()
        if first_error is not None:
            raise RuntimeError("Team member runtime cleanup did not finish cleanly.") from first_error


def _map_outcome(
    reason: StopReason,
    result: str,
    error: str | None,
    explicit_stop: bool,
) -> TeamMemberOutcome:
    if reason is StopReason.COMPLETED:
        kind = TeamMemberOutcomeKind.IDLE
    elif reason is StopReason.SAFE_PAUSE:
        kind = TeamMemberOutcomeKind.AWAITING_APPROVAL
    elif reason is StopReason.CANCELLED:
        kind = (
            TeamMemberOutcomeKind.STOPPED
            if explicit_stop
            else TeamMemberOutcomeKind.INTERRUPTED
        )
    else:
        kind = TeamMemberOutcomeKind.FAILED
    return TeamMemberOutcome(kind, result, error)


def _resume_prompt(state: TeamState, member: TeamMemberRecord, reason: str) -> str:
    task = state.tasks.get(member.current_task_id) if member.current_task_id else None
    task_text = (
        f"Current task {task.task_id}: {task.title}\n{task.description}"
        if task is not None
        else "No current task is assigned."
    )
    approval = (
        "approved"
        if task is not None and approval_is_valid(state, member.member_id, task.task_id)
        else ("required" if member.requires_approval else "not required")
    )
    return (
        f"Resume persistent team member {member.name.value} ({member.member_id}).\n"
        f"Reason: {reason.strip() or 'queued team work'}\n"
        f"{task_text}\nApproval state: {approval}."
    )
