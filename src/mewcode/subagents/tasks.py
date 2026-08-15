from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import time
from typing import Protocol
from uuid import uuid4

from mewcode.agent import AgentSubagentProgress, ForkRequestSeed
from mewcode.permissions import PermissionMode, PermissionRuleSets
from mewcode.prompting import PromptAdditions
from mewcode.providers import TokenUsage
from mewcode.tools import ToolRegistry, ToolSafety

from .models import (
    FOREGROUND_TIMEOUT_SECONDS,
    MAX_ACTIVE_TASKS,
    MAX_RESULT_CHARS,
    MAX_RETAINED_TASKS,
    TASK_CLOSE_TIMEOUT_SECONDS,
    SubagentDiagnostic,
    SubagentKind,
    SubagentNotification,
    SubagentParent,
    SubagentPlacement,
    SubagentProgress,
    SubagentTaskSnapshot,
    SubagentTaskStatus,
    SubagentTerminalEvent,
    TaskCancelResult,
    AgentDefinition,
    WorktreeTaskSummary,
)
from .notifications import SubagentNotificationQueue
from .policy import FrozenSubagentToolPolicy

evolve = getattr(dataclasses, "re" + "place")


@dataclass(frozen=True)
class SubagentDriverOutcome:
    status: SubagentTaskStatus
    result: str = ""
    error: str | None = None
    usage: TokenUsage = TokenUsage.zero()
    worktree: WorktreeTaskSummary | None = None


class SubagentTaskDriver(Protocol):
    def events(self) -> AsyncIterator[SubagentProgress]: ...

    @property
    def outcome(self) -> SubagentDriverOutcome: ...

    async def cancel(self) -> None: ...

    async def close(self) -> None: ...


DriverFactory = Callable[[str], SubagentTaskDriver | Awaitable[SubagentTaskDriver]]


@dataclass(frozen=True)
class SubagentLaunch:
    kind: SubagentKind
    role: str | None
    profile_name: str
    parent: SubagentParent
    placement: SubagentPlacement
    driver_factory: DriverFactory
    task_text: str = ""
    definition: AgentDefinition | None = None
    tools: ToolRegistry = field(default_factory=lambda: ToolRegistry([]))
    policy: FrozenSubagentToolPolicy = field(
        default_factory=lambda: FrozenSubagentToolPolicy(frozenset(), {})
    )
    permission_rules: PermissionRuleSets = PermissionRuleSets()
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    allowed_safety: frozenset[ToolSafety] = frozenset({ToolSafety.READ_ONLY})
    additions: PromptAdditions = PromptAdditions()
    seed: ForkRequestSeed | None = None


@dataclass
class _ManagedSubagentTask:
    snapshot: SubagentTaskSnapshot
    drive_task: asyncio.Task[None] | None
    driver: SubagentTaskDriver | None
    detached: asyncio.Event
    terminal: asyncio.Event
    updates: asyncio.Queue[SubagentProgress]
    registered_monotonic: float
    cancel_requested: bool = False
    cancel_forwarded: bool = False


class SubagentTaskHandle:
    def __init__(self, manager: SubagentTaskManager, task_id: str) -> None:
        self._manager = manager
        self.task_id = task_id

    @property
    def snapshot(self) -> SubagentTaskSnapshot | None:
        return self._manager.get(self.task_id)

    async def foreground_events(
        self,
        timeout: float = FOREGROUND_TIMEOUT_SECONDS,
    ) -> AsyncIterator[AgentSubagentProgress]:
        async for progress in self._manager._foreground_events(self.task_id, timeout):
            yield progress


class SubagentTaskManager:
    def __init__(
        self,
        notifications: SubagentNotificationQueue | None = None,
        *,
        max_active: int = MAX_ACTIVE_TASKS,
        retention_limit: int = MAX_RETAINED_TASKS,
        id_factory: Callable[[], str] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        close_timeout: float = TASK_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        if max_active < 1:
            raise ValueError("max_active must be at least 1")
        self._notifications = notifications or SubagentNotificationQueue()
        self._notifications.set_delivered_callback(self._notification_delivered)
        self._max_active = max_active
        self._retention_limit = retention_limit
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._sleep = sleep
        self._close_timeout = close_timeout
        self._lock = asyncio.Lock()
        self._records: dict[str, _ManagedSubagentTask] = {}
        self._current_foreground: str | None = None
        self._delivered_terminal: deque[str] = deque()
        self._terminal_events: asyncio.Queue[SubagentTerminalEvent | None] = asyncio.Queue()
        self._resetting = False
        self._closed = False

    @property
    def notifications(self) -> SubagentNotificationQueue:
        return self._notifications

    async def start(self, launch: SubagentLaunch) -> SubagentTaskHandle:
        async with self._lock:
            if self._closed:
                raise RuntimeError("The subagent task manager is closed.")
            if self._resetting:
                raise RuntimeError("The subagent task manager is resetting.")
            active = sum(record.snapshot.status.active for record in self._records.values())
            if active >= self._max_active:
                raise RuntimeError("The active subagent task limit has been reached.")
            if (
                launch.placement is SubagentPlacement.FOREGROUND
                and self._current_foreground is not None
            ):
                raise RuntimeError("Another foreground subagent task is already bound.")
            task_id = self._id_factory()
            if task_id in self._records:
                raise RuntimeError("The subagent task ID is not unique.")
            now = self._wall_clock()
            snapshot = SubagentTaskSnapshot(
                task_id=task_id,
                kind=launch.kind,
                status=SubagentTaskStatus.REGISTERED,
                placement=launch.placement,
                role=launch.role,
                profile_name=launch.profile_name,
                parent=launch.parent,
                created_at=now,
            )
            record = _ManagedSubagentTask(
                snapshot,
                None,
                None,
                asyncio.Event(),
                asyncio.Event(),
                asyncio.Queue(),
                self._monotonic(),
            )
            self._records[task_id] = record
            if launch.placement is SubagentPlacement.FOREGROUND:
                self._current_foreground = task_id
            record.drive_task = asyncio.create_task(self._drive(task_id, launch))
            return SubagentTaskHandle(self, task_id)

    def list(self) -> tuple[SubagentTaskSnapshot, ...]:
        values = [record.snapshot for record in self._records.values()]
        return tuple(sorted(values, key=lambda item: item.status.terminal))

    def get(self, task_id: str) -> SubagentTaskSnapshot | None:
        record = self._records.get(task_id)
        return record.snapshot if record is not None else None

    async def detach_foreground(self, task_id: str, reason: str) -> bool:
        del reason
        async with self._lock:
            record = self._records.get(task_id)
            if (
                record is None
                or record.snapshot.status.terminal
                or record.snapshot.placement is not SubagentPlacement.FOREGROUND
            ):
                return False
            record.snapshot = evolve(
                record.snapshot,
                placement=SubagentPlacement.BACKGROUND,
            )
            record.detached.set()
            if self._current_foreground == task_id:
                self._current_foreground = None
            return True

    async def detach_current_foreground(self, reason: str) -> str | None:
        task_id = self._current_foreground
        if task_id is None:
            return None
        return task_id if await self.detach_foreground(task_id, reason) else None

    async def cancel(self, task_id: str) -> TaskCancelResult:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return TaskCancelResult.NOT_FOUND
            if record.snapshot.status.terminal:
                return TaskCancelResult.ALREADY_TERMINAL
            if record.cancel_requested:
                return TaskCancelResult.ALREADY_REQUESTED
            record.cancel_requested = True
            driver = record.driver
            drive_task = record.drive_task
            if driver is not None:
                record.cancel_forwarded = True
        if driver is not None:
            try:
                await driver.cancel()
            except Exception:
                pass
        elif drive_task is not None:
            drive_task.cancel()
        if drive_task is not None and drive_task is not asyncio.current_task():
            await self._bounded_wait(drive_task)
        await self._commit_terminal(
            task_id,
            SubagentDriverOutcome(
                SubagentTaskStatus.CANCELLED,
                error="Subagent task was cancelled.",
            ),
        )
        return TaskCancelResult.REQUESTED

    async def terminal_events(self) -> AsyncIterator[SubagentTerminalEvent]:
        while True:
            event = await self._terminal_events.get()
            if event is None:
                return
            yield event

    async def reset(self) -> tuple[SubagentDiagnostic, ...]:
        async with self._lock:
            if self._closed:
                return ()
            if self._resetting:
                return ()
            self._resetting = True
            active_ids = [
                task_id
                for task_id, record in self._records.items()
                if record.snapshot.status.active
            ]
        diagnostics = await self._cancel_many(active_ids)
        async with self._lock:
            self._records.clear()
            self._current_foreground = None
            self._delivered_terminal.clear()
            self._notifications.clear()
            self._resetting = False
        return diagnostics

    async def close(self) -> tuple[SubagentDiagnostic, ...]:
        async with self._lock:
            if self._closed:
                return ()
            self._closed = True
            self._resetting = True
            active_ids = [
                task_id
                for task_id, record in self._records.items()
                if record.snapshot.status.active
            ]
        diagnostics = await self._cancel_many(active_ids)
        self._notifications.clear()
        self._terminal_events.put_nowait(None)
        return diagnostics

    async def _drive(self, task_id: str, launch: SubagentLaunch) -> None:
        driver: SubagentTaskDriver | None = None
        outcome = SubagentDriverOutcome(
            SubagentTaskStatus.FAILED,
            error="Subagent runtime did not produce an outcome.",
        )
        events_completed = False
        try:
            async with self._lock:
                record = self._records.get(task_id)
                if record is None:
                    return
                if not record.cancel_requested:
                    record.snapshot = evolve(
                        record.snapshot,
                        status=SubagentTaskStatus.RUNNING,
                        started_at=self._wall_clock(),
                    )
            created = launch.driver_factory(task_id)
            driver = await created if inspect.isawaitable(created) else created
            async with self._lock:
                record = self._records.get(task_id)
                if record is None:
                    return
                record.driver = driver
                cancel_now = record.cancel_requested and not record.cancel_forwarded
                if cancel_now:
                    record.cancel_forwarded = True
            if cancel_now:
                await driver.cancel()
            async for progress in driver.events():
                await self._record_progress(task_id, progress)
            outcome = driver.outcome
            events_completed = True
        except asyncio.CancelledError:
            outcome = SubagentDriverOutcome(
                SubagentTaskStatus.CANCELLED,
                error="Subagent task was cancelled.",
            )
        except Exception as exc:
            outcome = SubagentDriverOutcome(
                SubagentTaskStatus.FAILED,
                error=f"Subagent runtime failed: {type(exc).__name__}.",
            )
        finally:
            if driver is not None:
                try:
                    await driver.close()
                    try:
                        closed_outcome = driver.outcome
                        if events_completed or closed_outcome.worktree is not None:
                            outcome = closed_outcome
                    except RuntimeError:
                        pass
                except Exception:
                    if outcome.status is SubagentTaskStatus.COMPLETED:
                        outcome = SubagentDriverOutcome(
                            SubagentTaskStatus.FAILED,
                            result=outcome.result,
                            error="Subagent runtime cleanup failed.",
                            usage=outcome.usage,
                        )
            await self._commit_terminal(task_id, outcome)

    async def _record_progress(
        self,
        task_id: str,
        progress: SubagentProgress,
    ) -> None:
        bounded = SubagentProgress(
            progress.iteration,
            progress.phase[:128],
            progress.message,
        )
        async with self._lock:
            record = self._records.get(task_id)
            if record is None or record.snapshot.status.terminal:
                return
            record.snapshot = evolve(record.snapshot, progress=bounded)
            record.updates.put_nowait(bounded)

    async def _commit_terminal(
        self,
        task_id: str,
        outcome: SubagentDriverOutcome,
    ) -> None:
        status = outcome.status
        if not status.terminal:
            status = SubagentTaskStatus.FAILED
        result, result_cut = _truncate(outcome.result)
        error, error_cut = _truncate(outcome.error or "")
        async with self._lock:
            record = self._records.get(task_id)
            if record is None or record.snapshot.status.terminal:
                return
            if record.cancel_requested and status is not SubagentTaskStatus.COMPLETED:
                status = SubagentTaskStatus.CANCELLED
            pending = (
                record.snapshot.placement is SubagentPlacement.BACKGROUND
                and not self._resetting
            )
            finished = self._wall_clock()
            record.snapshot = evolve(
                record.snapshot,
                status=status,
                finished_at=finished,
                result=result,
                error=error or None,
                truncated=result_cut or error_cut,
                usage=outcome.usage,
                worktree=outcome.worktree,
                notification_pending=pending,
            )
            if self._current_foreground == task_id:
                self._current_foreground = None
            record.terminal.set()
            if pending:
                self._notifications.enqueue_once(
                    SubagentNotification(
                        task_id,
                        status,
                        record.snapshot.role,
                        result,
                        error or None,
                        result_cut or error_cut,
                        outcome.usage,
                        finished,
                        outcome.worktree,
                    )
                )
            self._terminal_events.put_nowait(
                SubagentTerminalEvent(
                    task_id,
                    status,
                    (result or error or status.value).splitlines()[0][:200],
                )
            )

    async def _foreground_events(
        self,
        task_id: str,
        timeout: float,
    ) -> AsyncIterator[AgentSubagentProgress]:
        record = self._records.get(task_id)
        if record is None:
            return
        remaining = max(0.0, timeout - (self._monotonic() - record.registered_monotonic))
        timeout_task = asyncio.create_task(self._sleep(remaining))
        try:
            while True:
                snapshot = record.snapshot
                if snapshot.status.terminal or record.detached.is_set():
                    return
                update_task = asyncio.create_task(record.updates.get())
                terminal_task = asyncio.create_task(record.terminal.wait())
                detached_task = asyncio.create_task(record.detached.wait())
                done, pending = await asyncio.wait(
                    (update_task, terminal_task, detached_task, timeout_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    if task is not timeout_task:
                        task.cancel()
                if timeout_task in done:
                    await self.detach_foreground(task_id, "foreground timeout")
                    return
                if terminal_task in done or detached_task in done:
                    return
                if update_task in done:
                    progress = update_task.result()
                    yield AgentSubagentProgress(
                        task_id,
                        "foreground",
                        progress.phase,
                        progress.message,
                    )
        finally:
            timeout_task.cancel()
            await asyncio.gather(timeout_task, return_exceptions=True)

    def _notification_delivered(self, task_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._mark_delivered(task_id))

    async def _mark_delivered(self, task_id: str) -> None:
        async with self._lock:
            record = self._records.get(task_id)
            if (
                record is None
                or not record.snapshot.status.terminal
                or not record.snapshot.notification_pending
            ):
                return
            record.snapshot = evolve(record.snapshot, notification_pending=False)
            self._delivered_terminal.append(task_id)
            while len(self._delivered_terminal) > self._retention_limit:
                oldest = self._delivered_terminal.popleft()
                candidate = self._records.get(oldest)
                if (
                    candidate is not None
                    and candidate.snapshot.status.terminal
                    and not candidate.snapshot.notification_pending
                ):
                    self._records.pop(oldest, None)

    async def _cancel_many(
        self,
        task_ids: list[str],
    ) -> tuple[SubagentDiagnostic, ...]:
        results = await asyncio.gather(
            *(self.cancel(task_id) for task_id in task_ids),
            return_exceptions=True,
        )
        diagnostics = []
        for task_id, result in zip(task_ids, results, strict=True):
            if isinstance(result, BaseException):
                diagnostics.append(
                    SubagentDiagnostic(task_id, "Subagent cancellation did not finish cleanly.")
                )
        return tuple(diagnostics)

    async def _bounded_wait(self, task: asyncio.Task[None]) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._close_timeout)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def _truncate(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_RESULT_CHARS:
        return value, False
    return value[:MAX_RESULT_CHARS] + "\n[truncated]", True
