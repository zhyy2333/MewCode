from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
import uuid

from mewcode.agent import AgentCapacityPool
from mewcode.locking import FileLock

from . import domain
from .models import (
    MemberWakeReason,
    SCHEMA_VERSION,
    TeamMemberOutcome,
    TeamMemberOutcomeKind,
    TeamMemberStatus,
    TeamMessage,
    TeamName,
    TeamOutboxEntry,
    TeamProtocol,
    TeamValidationError,
)
from .repository import TeamMutationRunner, TeamRepository
from .runtime import TeamMemberRuntime, TeamMemberRuntimeFactory

TEAM_CLOSE_TIMEOUT_SECONDS = 5.0


class TeamMemberScheduler:
    def __init__(
        self,
        repository: TeamRepository,
        team: TeamName,
        capacity: AgentCapacityPool,
        runtime_factory: TeamMemberRuntimeFactory,
        *,
        lease_fence: Callable[[], tuple[str, int]],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        close_timeout: float = TEAM_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self._repository = repository
        self._team = team
        self._capacity = capacity
        self._runtime_factory = runtime_factory
        self._lease_fence = lease_fence
        self._now = now
        self._new_id = new_id
        self._close_timeout = close_timeout
        self._mutations = TeamMutationRunner(repository)
        self._drivers: dict[str, asyncio.Task[None]] = {}
        self._runtimes: dict[str, TeamMemberRuntime] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def active_member_ids(self) -> tuple[str, ...]:
        return tuple(
            member_id
            for member_id, task in self._drivers.items()
            if not task.done()
        )

    async def restore(self) -> tuple[str, ...]:
        state = self._repository.load(self._team)
        restored: list[str] = []
        for entry in sorted(state.queue, key=lambda item: item.sequence):
            member = state.members.get(entry.member_id)
            if member is None or member.status is not TeamMemberStatus.QUEUED:
                continue
            if await self._ensure_driver(entry.member_id):
                restored.append(entry.member_id)
        return tuple(restored)

    async def request_wake(
        self,
        member_id: str,
        *,
        message_ids: Sequence[str],
        reason: MemberWakeReason = MemberWakeReason.MESSAGE,
    ) -> None:
        queue_id = self._new_id()

        def transform(state):
            candidate, _entry = domain.enqueue_member(
                state,
                member_id,
                queue_id=queue_id,
                reason=reason,
                message_ids=message_ids,
                now=self._now(),
            )
            return candidate

        committed = self._mutations.run(
            self._team,
            lease_fence=self._lease_fence(),
            transform=transform,
        )
        if any(item.member_id == member_id for item in committed.queue):
            await self._ensure_driver(member_id)

    async def stop(self, member_id: str) -> None:
        runtime = self._runtimes.get(member_id)
        if runtime is not None:
            await runtime.cancel(explicit_stop=True)
            return

        def transform(state):
            member = state.members.get(member_id)
            if member is None or member.status is TeamMemberStatus.STOPPED:
                return state
            if member.status is TeamMemberStatus.QUEUED:
                state = domain.dequeue_member(state, member_id, now=self._now())
                return domain.transition_member(
                    state,
                    member_id,
                    TeamMemberStatus.STOPPED,
                    now=self._now(),
                )
            return state

        self._mutations.run(
            self._team,
            lease_fence=self._lease_fence(),
            transform=transform,
        )
        task = self._drivers.get(member_id)
        if task is not None:
            task.cancel()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            runtimes = tuple(self._runtimes.values())
            tasks = tuple(self._drivers.values())
        await asyncio.gather(
            *(runtime.cancel(explicit_stop=False) for runtime in runtimes),
            return_exceptions=True,
        )
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self._close_timeout,
                )
            except asyncio.TimeoutError:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _ensure_driver(self, member_id: str) -> bool:
        async with self._lock:
            if self._closed:
                return False
            existing = self._drivers.get(member_id)
            if existing is not None and not existing.done():
                return False
            task = asyncio.create_task(self._drive(member_id))
            self._drivers[member_id] = task
            return True

    async def _drive(self, member_id: str) -> None:
        capacity_lease = None
        recovery_lock = FileLock(
            self._repository.paths(self._team).member_recovery_lock(member_id)
        )
        runtime: TeamMemberRuntime | None = None
        run_id: str | None = None
        generation: int | None = None
        outcome: TeamMemberOutcome | None = None
        try:
            capacity_lease = await self._capacity.acquire("team_member", member_id)
            if not await asyncio.to_thread(recovery_lock.acquire):
                return
            run_id = self._new_id()

            def start(state):
                member = state.members.get(member_id)
                if member is None or member.status is not TeamMemberStatus.QUEUED:
                    raise TeamValidationError("Queued member is no longer startable.")
                if not any(item.member_id == member_id for item in state.queue):
                    raise TeamValidationError("Member queue entry disappeared before start.")
                candidate = domain.dequeue_member(state, member_id, now=self._now())
                return domain.transition_member(
                    candidate,
                    member_id,
                    TeamMemberStatus.RUNNING,
                    now=self._now(),
                    active_run_id=run_id,
                )

            running = self._mutations.run(
                self._team,
                lease_fence=self._lease_fence(),
                transform=start,
            )
            generation = running.members[member_id].run_generation
            runtime = await self._runtime_factory.create(
                running,
                member_id,
                capacity_lease,
                reason="persistent wake queue",
            )
            capacity_lease = None  # owned by runtime
            self._runtimes[member_id] = runtime
            try:
                async for _progress in runtime.events():
                    pass
                outcome = runtime.outcome
            except asyncio.CancelledError:
                await runtime.cancel(explicit_stop=False)
                outcome = TeamMemberOutcome(TeamMemberOutcomeKind.INTERRUPTED, error="Scheduler closed.")
            except BaseException as exc:
                try:
                    outcome = runtime.outcome
                except RuntimeError:
                    outcome = TeamMemberOutcome(
                        TeamMemberOutcomeKind.FAILED,
                        error=f"Member execution failed: {type(exc).__name__}.",
                    )
        except asyncio.CancelledError:
            if run_id is not None:
                outcome = TeamMemberOutcome(TeamMemberOutcomeKind.INTERRUPTED, error="Scheduler closed.")
        except BaseException as exc:
            if run_id is not None:
                outcome = TeamMemberOutcome(
                    TeamMemberOutcomeKind.FAILED,
                    error=f"Member startup failed: {type(exc).__name__}.",
                )
        finally:
            if run_id is not None and generation is not None and outcome is not None:
                try:
                    self._commit_outcome(member_id, run_id, generation, outcome)
                except Exception:
                    pass
            self._runtimes.pop(member_id, None)
            if runtime is not None:
                try:
                    await runtime.close()
                except Exception:
                    pass
            if capacity_lease is not None:
                await capacity_lease.close()
            recovery_lock.close()
            async with self._lock:
                if self._drivers.get(member_id) is asyncio.current_task():
                    self._drivers.pop(member_id, None)

    def _commit_outcome(
        self,
        member_id: str,
        run_id: str,
        generation: int,
        outcome: TeamMemberOutcome,
    ) -> None:
        target = {
            TeamMemberOutcomeKind.IDLE: TeamMemberStatus.IDLE,
            TeamMemberOutcomeKind.AWAITING_APPROVAL: TeamMemberStatus.AWAITING_APPROVAL,
            TeamMemberOutcomeKind.STOPPED: TeamMemberStatus.STOPPED,
            TeamMemberOutcomeKind.INTERRUPTED: TeamMemberStatus.INTERRUPTED,
            TeamMemberOutcomeKind.FAILED: TeamMemberStatus.FAILED,
        }[outcome.kind]

        def transform(state):
            member = state.members.get(member_id)
            if member is None:
                raise TeamValidationError("Member was removed before its result arrived.")
            if member.active_run_id != run_id or member.run_generation != generation:
                if member.status is TeamMemberStatus.STOPPED and target is TeamMemberStatus.STOPPED:
                    return state
                raise TeamValidationError("Stale member runtime result was rejected.")
            candidate = domain.transition_member(
                state,
                member_id,
                target,
                now=self._now(),
                error=outcome.error,
            )
            if outcome.kind in {TeamMemberOutcomeKind.IDLE, TeamMemberOutcomeKind.FAILED}:
                candidate = self._notify_lead(candidate, member_id, outcome)
            return candidate

        self._mutations.run(
            self._team,
            lease_fence=self._lease_fence(),
            transform=transform,
        )

    def _notify_lead(self, state, member_id: str, outcome: TeamMemberOutcome):
        lead = next((item for item in state.registry.values() if item.is_lead), None)
        if lead is None:
            return state
        summary = (
            f"Member {member_id} is idle"
            if outcome.kind is TeamMemberOutcomeKind.IDLE
            else f"Member {member_id} failed"
        )
        body = outcome.result_summary or outcome.error or summary
        message = TeamMessage(
            SCHEMA_VERSION,
            self._new_id(),
            None,
            member_id,
            lead.participant_id,
            summary[:256],
            body[:4096],
            TeamProtocol.MEMBER_IDLE,
            {"member_id": member_id, "outcome": outcome.kind.value},
            self._now(),
        )
        entry = TeamOutboxEntry(self._new_id(), message, False, self._now())
        return replace(state, outbox=(*state.outbox, entry), updated_at=self._now())
