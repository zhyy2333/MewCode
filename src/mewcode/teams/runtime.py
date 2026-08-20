from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import asyncio
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
from .control import (
    ControlCancelRequest,
    ControlRunRequest,
    MemberControlBroker,
    PaneHostConnection,
)
from .models import (
    TeamMemberBackend,
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


@dataclass
class TeamMemberExecution:
    member: TeamMemberRecord
    bundle: TeamMemberRunBundle
    session: MemberSessionBinding
    worktree_lease: WorktreeLease
    worktrees: WorktreeLifecycleService
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        try:
            await self.bundle.close()
        except BaseException as exc:
            first_error = exc
        try:
            self.session.close()
        except BaseException as exc:
            first_error = first_error or exc
        try:
            await self.worktrees.suspend(self.worktree_lease)
        except BaseException as exc:
            first_error = first_error or exc
        if first_error is not None:
            raise RuntimeError("Team member execution cleanup did not finish cleanly.") from first_error


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
        execution: TeamMemberExecution | None = None
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
        try:
            execution = await self.assemble(state, member_id, reason=reason)
            return TeamMemberRuntime(execution, capacity_lease)
        except BaseException:
            if execution is not None:
                await execution.close()
            await capacity_lease.close()
            raise

    async def assemble(
        self,
        state: TeamState,
        member_id: str,
        *,
        reason: str,
    ) -> TeamMemberExecution:
        """Assemble one member run without acquiring or owning Lead capacity."""
        try:
            member = state.members[member_id]
        except KeyError as exc:
            raise TeamValidationError("Unknown team member runtime identity.") from exc
        if member.status is not TeamMemberStatus.RUNNING or member.active_run_id is None:
            raise TeamValidationError("Member runtime requires a committed RUNNING state.")
        expected_name = self._names.for_team_member(state.manifest.team_id, member_id)
        if expected_name.value != member.worktree_name:
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
            return TeamMemberExecution(
                member,
                bundle,
                session,
                worktree_lease,
                self._worktrees,
            )
        except BaseException:
            if bundle is not None:
                await bundle.close()
            if session is not None:
                session.close()
            if worktree_lease is not None:
                await self._worktrees.suspend(worktree_lease)
            raise


class TeamMemberRuntime:
    def __init__(
        self,
        execution: TeamMemberExecution,
        capacity_lease: AgentCapacityLease,
    ) -> None:
        self.member = execution.member
        self._execution = execution
        self._bundle = execution.bundle
        self._capacity_lease = capacity_lease
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
            await self._execution.close()
        except BaseException as exc:
            first_error = exc
        finally:
            await self._capacity_lease.close()
        if first_error is not None:
            raise RuntimeError("Team member runtime cleanup did not finish cleanly.") from first_error


TerminalConnectionResolver = Callable[[TeamMemberRecord], Awaitable[PaneHostConnection]]


class TerminalMemberRuntimeFactory:
    def __init__(
        self,
        broker: MemberControlBroker,
        *,
        ensure_connection: TerminalConnectionResolver | None = None,
    ) -> None:
        self._broker = broker
        self._ensure_connection = ensure_connection

    async def create(
        self,
        state: TeamState,
        member_id: str,
        capacity_lease: AgentCapacityLease,
        *,
        reason: str,
    ) -> TerminalMemberRuntime:
        try:
            member = state.members[member_id]
            if member.backend is TeamMemberBackend.IN_PROCESS:
                raise TeamValidationError("Terminal runtime requires an isolated member backend.")
            if member.status is not TeamMemberStatus.RUNNING or member.active_run_id is None:
                raise TeamValidationError("Terminal runtime requires a committed RUNNING state.")
            if capacity_lease.owner_id != member_id:
                raise TeamValidationError("Capacity lease belongs to another member.")
            connection = self._broker.connection(member_id)
            if connection is None:
                if self._ensure_connection is None:
                    raise TeamValidationError("Terminal pane host is unavailable.")
                connection = await self._ensure_connection(member)
            if connection.registration.member_id != member_id:
                raise TeamValidationError("Terminal pane host identity does not match the member.")
            return TerminalMemberRuntime(member, connection, capacity_lease, reason=reason)
        except BaseException:
            await capacity_lease.close()
            raise


class TerminalMemberRuntime:
    def __init__(
        self,
        member: TeamMemberRecord,
        connection: PaneHostConnection,
        capacity_lease: AgentCapacityLease,
        *,
        reason: str,
    ) -> None:
        if member.active_run_id is None:
            raise TeamValidationError("Terminal runtime member has no active run.")
        self.member = member
        self._connection = connection
        self._capacity_lease = capacity_lease
        self._reason = reason
        self._outcome: TeamMemberOutcome | None = None
        self._started = False
        self._explicit_stop = False
        self._closed = False

    async def events(self) -> AsyncIterator[TeamMemberProgress]:
        if self._started:
            raise TeamValidationError("Terminal member runtime can only be started once.")
        self._started = True
        run_id = self.member.active_run_id
        assert run_id is not None
        await self._connection.request_run(
            ControlRunRequest(run_id, self.member.run_generation, self._reason)
        )
        while True:
            result_waiter = asyncio.create_task(self._connection.next_result())
            progress_waiter = asyncio.create_task(self._connection.next_progress())
            done, pending = await asyncio.wait(
                (result_waiter, progress_waiter),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if result_waiter in done:
                if progress_waiter in done:
                    progress = progress_waiter.result()
                    if progress.run_id != run_id or progress.run_generation != self.member.run_generation:
                        raise TeamValidationError("Stale terminal member progress was rejected.")
                    yield TeamMemberProgress(progress.phase, progress.message)
                else:
                    progress_waiter.cancel()
                    await asyncio.gather(progress_waiter, return_exceptions=True)
                result = result_waiter.result()
                if result.run_id != run_id or result.run_generation != self.member.run_generation:
                    raise TeamValidationError("Stale terminal member result was rejected.")
                kind = TeamMemberOutcomeKind(result.outcome)
                if self._explicit_stop and kind is TeamMemberOutcomeKind.INTERRUPTED:
                    kind = TeamMemberOutcomeKind.STOPPED
                self._outcome = TeamMemberOutcome(
                    kind,
                    result.result_summary,
                    result.diagnostic,
                )
                return
            result_waiter.cancel()
            await asyncio.gather(result_waiter, return_exceptions=True)
            progress = progress_waiter.result()
            if progress.run_id != run_id or progress.run_generation != self.member.run_generation:
                raise TeamValidationError("Stale terminal member progress was rejected.")
            yield TeamMemberProgress(progress.phase, progress.message)

    @property
    def outcome(self) -> TeamMemberOutcome:
        if self._outcome is None:
            raise RuntimeError("Terminal member runtime has not reached an outcome.")
        return self._outcome

    async def cancel(self, *, explicit_stop: bool = False) -> None:
        self._explicit_stop = self._explicit_stop or explicit_stop
        if not self._started or self._outcome is not None:
            return
        run_id = self.member.active_run_id
        assert run_id is not None
        await self._connection.request_cancel(
            ControlCancelRequest(run_id, self.member.run_generation, self._explicit_stop)
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._capacity_lease.close()


class TeamMemberRuntimeRouter:
    """Route once-persisted member backends without applying fallback."""

    def __init__(
        self,
        in_process: TeamMemberRuntimeFactory,
        terminal: TerminalMemberRuntimeFactory,
    ) -> None:
        self._in_process = in_process
        self._terminal = terminal

    async def create(
        self,
        state: TeamState,
        member_id: str,
        capacity_lease: AgentCapacityLease,
        *,
        reason: str,
    ) -> TeamMemberRuntime | TerminalMemberRuntime:
        try:
            member = state.members[member_id]
        except KeyError as exc:
            await capacity_lease.close()
            raise TeamValidationError("Unknown team member runtime identity.") from exc
        factory = (
            self._in_process
            if member.backend is TeamMemberBackend.IN_PROCESS
            else self._terminal
        )
        return await factory.create(
            state,
            member_id,
            capacity_lease,
            reason=reason,
        )


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
