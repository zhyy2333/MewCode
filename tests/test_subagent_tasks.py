from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from mewcode.agent import AgentCapacityPool, AgentSubagentProgress
from mewcode.providers import TokenUsage
from mewcode.subagents import (
    SUBAGENT_EXECUTION_TIMEOUT_SECONDS,
    SubagentDriverOutcome,
    SubagentKind,
    SubagentLaunch,
    SubagentNotificationQueue,
    SubagentParent,
    SubagentPlacement,
    SubagentProgress,
    SubagentTaskManager,
    SubagentTaskStatus,
    TaskCancelResult,
    WorktreeTaskSummary,
)
from tests.fakes import collect_async


class FakeDriver:
    def __init__(
        self,
        outcome: SubagentDriverOutcome | None = None,
        *,
        gate: asyncio.Event | None = None,
        fail: BaseException | None = None,
        cancel_fail: bool = False,
        cleanup_fail: bool = False,
    ) -> None:
        self._outcome = outcome or SubagentDriverOutcome(
            SubagentTaskStatus.COMPLETED,
            "done",
            usage=TokenUsage(3, 2, 5),
        )
        self.gate = gate
        self.fail = fail
        self.cancel_fail = cancel_fail
        self.cleanup_fail = cleanup_fail
        self.events_calls = 0
        self.cancel_calls = 0
        self.close_calls = 0

    async def events(self):
        self.events_calls += 1
        yield SubagentProgress(1, "model", "working")
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail

    @property
    def outcome(self):
        return self._outcome

    async def cancel(self):
        self.cancel_calls += 1
        self._outcome = SubagentDriverOutcome(
            SubagentTaskStatus.CANCELLED,
            error="cancelled",
            usage=self._outcome.usage,
            worktree=self._outcome.worktree,
        )
        if self.gate is not None:
            self.gate.set()
        if self.cancel_fail:
            raise RuntimeError("cancel cleanup")

    async def close(self):
        self.close_calls += 1
        if self.cleanup_fail:
            raise RuntimeError("cleanup")


def _launch(
    factory,
    *,
    placement: SubagentPlacement = SubagentPlacement.FOREGROUND,
    kind: SubagentKind = SubagentKind.DEFINED,
):
    return SubagentLaunch(
        kind,
        "reviewer" if kind is SubagentKind.DEFINED else None,
        "main",
        SubagentParent("parent", 2),
        placement,
        factory,
    )


def test_shared_capacity_is_released_on_every_subagent_terminal_path() -> None:
    async def scenario() -> None:
        pool = AgentCapacityPool(2)
        team_lease = await pool.acquire("team_member", "member-1")
        gate = asyncio.Event()
        ids = iter(("sub-1", "sub-2", "sub-3"))
        manager = SubagentTaskManager(
            capacity_pool=pool,
            id_factory=lambda: next(ids),
        )
        await manager.start(
            _launch(
                lambda task_id: FakeDriver(gate=gate),
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        with pytest.raises(RuntimeError, match="active subagent task limit"):
            await manager.start(
                _launch(
                    lambda task_id: FakeDriver(),
                    placement=SubagentPlacement.BACKGROUND,
                )
            )
        gate.set()
        await _settle()
        await manager.start(
            _launch(
                lambda task_id: FakeDriver(),
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        assert pool.active_count == 1
        await manager.close()
        await team_lease.close()

    asyncio.run(scenario())


async def _settle() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


class ControlledSleeper:
    def __init__(self) -> None:
        self.calls: list[tuple[float, asyncio.Future[None]]] = []

    async def __call__(self, delay: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self.calls.append((delay, future))
        await future

    def release(self, delay: float) -> None:
        for actual, future in self.calls:
            if actual == pytest.approx(delay) and not future.done():
                future.set_result(None)
                return
        raise AssertionError(f"No pending sleep for {delay} seconds.")


def test_public_models_are_frozen_and_status_classification_is_stable() -> None:
    parent = SubagentParent("run", 1)
    with pytest.raises(FrozenInstanceError):
        parent.run_id = "changed"  # type: ignore[misc]
    assert [status.value for status in SubagentTaskStatus] == [
        "registered",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    assert SubagentTaskStatus.REGISTERED.active
    assert SubagentTaskStatus.RUNNING.active
    assert SubagentTaskStatus.COMPLETED.terminal


def test_quick_foreground_completion_updates_snapshot_and_cleans_once() -> None:
    async def scenario():
        driver = FakeDriver()
        manager = SubagentTaskManager(id_factory=lambda: "task-1")
        handle = await manager.start(_launch(lambda task_id: driver))
        events = await collect_async(handle.foreground_events())
        await _settle()
        snapshot = manager.get("task-1")
        await manager.close()
        return driver, events, snapshot

    driver, events, snapshot = asyncio.run(scenario())
    assert all(isinstance(event, AgentSubagentProgress) for event in events)
    assert snapshot.status is SubagentTaskStatus.COMPLETED
    assert snapshot.result == "done"
    assert snapshot.usage == TokenUsage(3, 2, 5)
    assert snapshot.notification_pending is False
    assert driver.events_calls == driver.close_calls == 1


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (SubagentDriverOutcome(SubagentTaskStatus.FAILED, error="bad"), SubagentTaskStatus.FAILED),
        (SubagentDriverOutcome(SubagentTaskStatus.CANCELLED, error="stop"), SubagentTaskStatus.CANCELLED),
        (SubagentDriverOutcome(SubagentTaskStatus.RUNNING), SubagentTaskStatus.FAILED),
    ],
)
def test_driver_outcomes_map_to_one_terminal_state(outcome, expected) -> None:
    async def scenario():
        manager = SubagentTaskManager(id_factory=lambda: "task")
        await manager.start(_launch(lambda task_id: FakeDriver(outcome)))
        await _settle()
        snapshot = manager.get("task")
        await manager.close()
        return snapshot

    assert asyncio.run(scenario()).status is expected


def test_factory_event_and_cleanup_failures_are_safe() -> None:
    async def scenario():
        ids = iter(("factory", "event", "cleanup"))
        manager = SubagentTaskManager(id_factory=lambda: next(ids))

        def broken_factory(task_id):
            raise RuntimeError("secret factory")

        await manager.start(_launch(broken_factory, placement=SubagentPlacement.BACKGROUND))
        await manager.start(
            _launch(
                lambda task_id: FakeDriver(fail=RuntimeError("secret event")),
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await manager.start(
            _launch(
                lambda task_id: FakeDriver(cleanup_fail=True),
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        snapshots = manager.list()
        await manager.close()
        return snapshots

    snapshots = asyncio.run(scenario())
    assert all(item.status is SubagentTaskStatus.FAILED for item in snapshots)
    assert all("secret" not in (item.error or "") for item in snapshots)


def test_concurrent_registration_never_exceeds_capacity() -> None:
    async def scenario():
        gate = asyncio.Event()
        counter = 0

        def next_id():
            nonlocal counter
            counter += 1
            return f"task-{counter}"

        manager = SubagentTaskManager(max_active=2, id_factory=next_id)
        results = await asyncio.gather(
            *(
                manager.start(
                    _launch(
                        lambda task_id: FakeDriver(gate=gate),
                        placement=SubagentPlacement.BACKGROUND,
                    )
                )
                for _ in range(5)
            ),
            return_exceptions=True,
        )
        successes = [item for item in results if not isinstance(item, BaseException)]
        failures = [item for item in results if isinstance(item, BaseException)]
        gate.set()
        await _settle()
        await manager.close()
        return successes, failures

    successes, failures = asyncio.run(scenario())
    assert len(successes) == 2
    assert len(failures) == 3


def test_manual_detach_does_not_restart_and_completion_notifies_once() -> None:
    async def scenario():
        gate = asyncio.Event()
        driver = FakeDriver(gate=gate)
        notifications = SubagentNotificationQueue()
        manager = SubagentTaskManager(notifications, id_factory=lambda: "task")
        handle = await manager.start(_launch(lambda task_id: driver))
        await _settle()
        assert await manager.detach_current_foreground("ctrl+b") == "task"
        assert await manager.detach_current_foreground("again") is None
        gate.set()
        await _settle()
        snapshot = manager.get("task")
        batch = notifications.consume_batch()
        await _settle()
        delivered = manager.get("task")
        await manager.close()
        return handle, driver, snapshot, batch, delivered

    _, driver, snapshot, batch, delivered = asyncio.run(scenario())
    assert driver.events_calls == 1
    assert snapshot.placement is SubagentPlacement.BACKGROUND
    assert snapshot.notification_pending is True
    assert [item.task_id for item in batch.notifications] == ["task"]
    assert delivered.notification_pending is False


def test_timeout_detaches_in_place_without_real_wait() -> None:
    async def immediate_sleep(delay):
        await asyncio.sleep(0)

    async def scenario():
        gate = asyncio.Event()
        driver = FakeDriver(gate=gate)
        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            sleep=immediate_sleep,
        )
        handle = await manager.start(_launch(lambda task_id: driver))
        await collect_async(handle.foreground_events())
        snapshot = manager.get("task")
        gate.set()
        await _settle()
        await manager.close()
        return driver, snapshot

    driver, snapshot = asyncio.run(scenario())
    assert snapshot.placement is SubagentPlacement.BACKGROUND
    assert driver.events_calls == 1


def test_cancel_is_forwarded_once_and_results_are_deterministic() -> None:
    async def scenario():
        gate = asyncio.Event()
        driver = FakeDriver(gate=gate)
        manager = SubagentTaskManager(id_factory=lambda: "task", close_timeout=0.01)
        await manager.start(_launch(lambda task_id: driver))
        await _settle()
        first = await manager.cancel("task")
        second = await manager.cancel("task")
        unknown = await manager.cancel("missing")
        snapshot = manager.get("task")
        await manager.close()
        return driver, first, second, unknown, snapshot

    driver, first, second, unknown, snapshot = asyncio.run(scenario())
    assert first is TaskCancelResult.REQUESTED
    assert second is TaskCancelResult.ALREADY_TERMINAL
    assert unknown is TaskCancelResult.NOT_FOUND
    assert driver.cancel_calls == 1
    assert snapshot.status is SubagentTaskStatus.CANCELLED


def test_cancel_registered_task_commits_cancelled_without_starting_driver() -> None:
    async def scenario():
        calls = []
        manager = SubagentTaskManager(id_factory=lambda: "task", close_timeout=0.01)
        await manager.start(
            _launch(lambda task_id: calls.append(task_id) or FakeDriver())
        )
        result = await manager.cancel("task")
        snapshot = manager.get("task")
        await manager.close()
        return calls, result, snapshot

    calls, result, snapshot = asyncio.run(scenario())
    assert calls == []
    assert result is TaskCancelResult.REQUESTED
    assert snapshot.status is SubagentTaskStatus.CANCELLED


def test_foreground_timeout_is_measured_from_registration() -> None:
    async def scenario():
        now = 100.0
        sleeper = ControlledSleeper()

        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            monotonic=lambda: now,
            sleep=sleeper,
        )
        gate = asyncio.Event()
        handle = await manager.start(_launch(lambda task_id: FakeDriver(gate=gate)))
        now = 106.0
        foreground = asyncio.create_task(
            collect_async(handle.foreground_events(timeout=10.0))
        )
        await _settle()
        sleeper.release(4.0)
        await foreground
        gate.set()
        await _settle()
        delays = sorted(delay for delay, _ in sleeper.calls)
        await manager.close()
        return delays

    assert asyncio.run(scenario()) == [4.0, 294.0]


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_execution_timeout_config_requires_a_positive_finite_value(value) -> None:
    with pytest.raises(ValueError, match="execution_timeout"):
        SubagentTaskManager(execution_timeout=value)


def test_execution_timeout_fails_and_cleans_a_background_driver() -> None:
    async def scenario():
        gate = asyncio.Event()
        sleeper = ControlledSleeper()
        driver = FakeDriver(gate=gate)
        notifications = SubagentNotificationQueue()
        manager = SubagentTaskManager(
            notifications,
            id_factory=lambda: "task",
            sleep=sleeper,
            execution_timeout=SUBAGENT_EXECUTION_TIMEOUT_SECONDS,
        )
        await manager.start(
            _launch(
                lambda task_id: driver,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()

        sleeper.release(SUBAGENT_EXECUTION_TIMEOUT_SECONDS)
        await _settle()
        snapshot = manager.get("task")
        batch = notifications.consume_batch()
        await manager.close()
        return driver, snapshot, batch

    driver, snapshot, batch = asyncio.run(scenario())

    assert snapshot.status is SubagentTaskStatus.FAILED
    assert snapshot.error == "Subagent task exceeded its 300-second execution timeout."
    assert snapshot.usage == TokenUsage(3, 2, 5)
    assert driver.cancel_calls == 1
    assert driver.close_calls == 1
    assert [item.task_id for item in batch.notifications] == ["task"]
    assert batch.notifications[0].status is SubagentTaskStatus.FAILED


def test_execution_timeout_handles_driver_factory_failure() -> None:
    async def scenario():
        sleeper = ControlledSleeper()
        factory_started = asyncio.Event()
        factory_cancelled = asyncio.Event()

        async def blocked_factory(task_id):
            factory_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                factory_cancelled.set()
                raise

        manager = SubagentTaskManager(
            id_factory=lambda: "factory-task",
            sleep=sleeper,
            execution_timeout=300.0,
        )
        await manager.start(
            _launch(
                blocked_factory,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await factory_started.wait()
        sleeper.release(300.0)
        await _settle()
        snapshot = manager.get("factory-task")
        await manager.close()
        return snapshot, factory_cancelled.is_set()

    snapshot, factory_cancelled = asyncio.run(scenario())

    assert factory_cancelled is True
    assert snapshot.status is SubagentTaskStatus.FAILED
    assert snapshot.error == "Subagent task exceeded its 300-second execution timeout."


def test_detach_deadline_does_not_restart_execution() -> None:
    async def scenario():
        gate = asyncio.Event()
        sleeper = ControlledSleeper()
        driver = FakeDriver(gate=gate)
        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            sleep=sleeper,
            execution_timeout=300.0,
        )
        handle = await manager.start(_launch(lambda task_id: driver))
        await _settle()
        foreground = asyncio.create_task(
            collect_async(handle.foreground_events(timeout=10.0))
        )
        await _settle()

        sleeper.release(10.0)
        await foreground
        detached = manager.get("task")
        sleeper.release(300.0)
        await _settle()
        terminal = manager.get("task")
        calls = [delay for delay, _ in sleeper.calls]
        await manager.close()
        return driver, detached, terminal, calls

    driver, detached, terminal, calls = asyncio.run(scenario())

    assert detached.placement is SubagentPlacement.BACKGROUND
    assert terminal.status is SubagentTaskStatus.FAILED
    assert calls.count(300.0) == 1
    assert calls.count(10.0) == 1
    assert driver.events_calls == 1


def test_execution_timeout_race_preserves_failed_when_timeout_wins_cancel() -> None:
    class BlockingCancelDriver(FakeDriver):
        def __init__(self):
            super().__init__(gate=asyncio.Event())
            self.cancel_started = asyncio.Event()
            self.cancel_release = asyncio.Event()

        async def cancel(self):
            self.cancel_calls += 1
            self.cancel_started.set()
            await self.cancel_release.wait()
            self._outcome = SubagentDriverOutcome(
                SubagentTaskStatus.CANCELLED,
                error="cancelled",
                usage=TokenUsage(3, 2, 5),
            )
            self.gate.set()

    async def scenario():
        sleeper = ControlledSleeper()
        driver = BlockingCancelDriver()
        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            sleep=sleeper,
            execution_timeout=300.0,
        )
        await manager.start(
            _launch(
                lambda task_id: driver,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()

        sleeper.release(300.0)
        await driver.cancel_started.wait()
        cancel_result = await manager.cancel("task")
        driver.cancel_release.set()
        await _settle()
        snapshot = manager.get("task")
        await manager.close()
        return driver, cancel_result, snapshot

    driver, cancel_result, snapshot = asyncio.run(scenario())

    assert cancel_result is TaskCancelResult.ALREADY_REQUESTED
    assert driver.cancel_calls == 1
    assert snapshot.status is SubagentTaskStatus.FAILED
    assert snapshot.error == "Subagent task exceeded its 300-second execution timeout."


def test_execution_timeout_race_preserves_cancelled_when_user_cancel_wins() -> None:
    async def scenario():
        sleeper = ControlledSleeper()
        driver = FakeDriver(gate=asyncio.Event())
        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            sleep=sleeper,
            execution_timeout=300.0,
        )
        await manager.start(
            _launch(
                lambda task_id: driver,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        result = await manager.cancel("task")
        snapshot = manager.get("task")
        await manager.close()
        return driver, result, snapshot

    driver, result, snapshot = asyncio.run(scenario())

    assert result is TaskCancelResult.REQUESTED
    assert driver.cancel_calls == 1
    assert snapshot.status is SubagentTaskStatus.CANCELLED


def test_execution_timeout_race_prefers_completed_driver_when_both_ready() -> None:
    class ImmediateDriver(FakeDriver):
        async def events(self):
            self.events_calls += 1
            if False:
                yield SubagentProgress(1, "unused", "unused")

    async def immediate_sleep(delay):
        return None

    async def scenario():
        driver = ImmediateDriver()
        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            sleep=immediate_sleep,
            execution_timeout=300.0,
        )
        await manager.start(
            _launch(
                lambda task_id: driver,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        snapshot = manager.get("task")
        await manager.close()
        return driver, snapshot

    driver, snapshot = asyncio.run(scenario())

    assert driver.cancel_calls == 0
    assert snapshot.status is SubagentTaskStatus.COMPLETED
    assert snapshot.result == "done"


def test_execution_timeout_preserves_worktree_cleanup_summary() -> None:
    async def scenario():
        sleeper = ControlledSleeper()
        summary = WorktreeTaskSummary(
            "retained",
            "C:/workspace/.mewcode/worktrees/task",
            "refs/heads/mewcode/task",
        )
        driver = FakeDriver(
            SubagentDriverOutcome(
                SubagentTaskStatus.COMPLETED,
                "unused",
                usage=TokenUsage(7, 3, 10),
                worktree=summary,
            ),
            gate=asyncio.Event(),
        )
        manager = SubagentTaskManager(
            id_factory=lambda: "task",
            sleep=sleeper,
            execution_timeout=300.0,
        )
        await manager.start(
            _launch(
                lambda task_id: driver,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        sleeper.release(300.0)
        await _settle()
        snapshot = manager.get("task")
        await manager.close()
        return summary, snapshot

    summary, snapshot = asyncio.run(scenario())

    assert snapshot.status is SubagentTaskStatus.FAILED
    assert snapshot.worktree == summary
    assert snapshot.usage == TokenUsage(7, 3, 10)


def test_execution_timeout_handles_cancel_and_close_failure() -> None:
    async def scenario():
        sleeper = ControlledSleeper()
        timed_out = FakeDriver(
            gate=asyncio.Event(),
            cancel_fail=True,
            cleanup_fail=True,
        )
        ids = iter(("timed-out", "next"))
        manager = SubagentTaskManager(
            id_factory=lambda: next(ids),
            sleep=sleeper,
            execution_timeout=300.0,
        )
        await manager.start(
            _launch(
                lambda task_id: timed_out,
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        sleeper.release(300.0)
        await _settle()
        first = manager.get("timed-out")

        await manager.start(
            _launch(
                lambda task_id: FakeDriver(),
                placement=SubagentPlacement.BACKGROUND,
            )
        )
        await _settle()
        second = manager.get("next")
        await manager.close()
        return first, second, timed_out

    first, second, timed_out = asyncio.run(scenario())

    assert first.status is SubagentTaskStatus.FAILED
    assert first.error == "Subagent task exceeded its 300-second execution timeout."
    assert second.status is SubagentTaskStatus.COMPLETED
    assert timed_out.cancel_calls == 1
    assert timed_out.close_calls == 1


def test_terminal_events_are_once_and_close_ends_stream() -> None:
    async def scenario():
        manager = SubagentTaskManager(id_factory=lambda: "task")
        stream = manager.terminal_events()
        await manager.start(_launch(lambda task_id: FakeDriver()))
        event = await anext(stream)
        await manager.close()
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        return event

    event = asyncio.run(scenario())
    assert event.task_id == "task"
    assert event.status is SubagentTaskStatus.COMPLETED
    assert event.summary == "done"


def test_reset_cancels_clears_and_allows_new_tasks() -> None:
    async def scenario():
        gate = asyncio.Event()
        ids = iter(("old", "new"))
        manager = SubagentTaskManager(id_factory=lambda: next(ids), close_timeout=0.01)
        await manager.start(
            _launch(lambda task_id: FakeDriver(gate=gate), placement=SubagentPlacement.BACKGROUND)
        )
        await _settle()
        diagnostics = await manager.reset()
        assert manager.list() == ()
        await manager.start(_launch(lambda task_id: FakeDriver()))
        await _settle()
        new = manager.get("new")
        await manager.close()
        return diagnostics, new

    diagnostics, new = asyncio.run(scenario())
    assert diagnostics == ()
    assert new.status is SubagentTaskStatus.COMPLETED


def test_retention_evicts_only_delivered_background_terminal_tasks() -> None:
    async def scenario():
        ids = iter(("one", "two", "three"))
        notifications = SubagentNotificationQueue()
        manager = SubagentTaskManager(
            notifications,
            id_factory=lambda: next(ids),
            retention_limit=2,
        )
        for _ in range(3):
            await manager.start(
                _launch(lambda task_id: FakeDriver(), placement=SubagentPlacement.BACKGROUND)
            )
        await _settle()
        notifications.consume_batch()
        await _settle()
        remaining = [item.task_id for item in manager.list()]
        await manager.close()
        return remaining

    assert asyncio.run(scenario()) == ["two", "three"]


def test_close_is_idempotent_and_rejects_new_tasks() -> None:
    async def scenario():
        manager = SubagentTaskManager()
        assert await manager.close() == ()
        assert await manager.close() == ()
        with pytest.raises(RuntimeError, match="closed"):
            await manager.start(_launch(lambda task_id: FakeDriver()))

    asyncio.run(scenario())
