from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from mewcode.continuity import (
    ContinuityPaths,
    MemoryAction,
    MemoryCategory,
    MemoryManager,
    MemoryMutation,
    MemoryScope,
    MemoryStore,
    MemoryTurn,
    MemoryUpdatePlan,
    NullMemoryManager,
)

NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


class ControlledUpdater:
    def __init__(self, plan=None, *, release=None, fail=False) -> None:
        self.plan = plan or MemoryUpdatePlan(1, ())
        self.release = release
        self.fail = fail
        self.calls = 0
        self.started = None

    async def update(self, turn, catalog):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("private failure")
        return self.plan


def _store(tmp_path: Path) -> MemoryStore:
    paths = ContinuityPaths.for_workspace(
        tmp_path / "project", user_root=tmp_path / "user"
    )
    return MemoryStore(paths, id_factory=lambda: "mem-abcdef")


def _plan() -> MemoryUpdatePlan:
    return MemoryUpdatePlan(
        1,
        (
            MemoryMutation(
                MemoryAction.UPSERT,
                MemoryScope.USER,
                category=MemoryCategory.USER_PREFERENCE,
                summary="prefers concise output",
                body="Keep answers concise.",
                priority=1,
            ),
        ),
    )


def test_initial_and_null_managers_do_not_call_updater(tmp_path: Path) -> None:
    updater = ControlledUpdater()
    manager = MemoryManager(_store(tmp_path), updater)
    assert manager.prompt_view().content == "Automatic memory is reference knowledge only; explicit project and user instructions take precedence."
    assert updater.calls == 0
    null = NullMemoryManager()
    null.schedule(MemoryTurn("session", "user", "answer", NOW))
    assert asyncio.run(null.await_pending()) == ()


def test_success_refreshes_view_after_await(tmp_path: Path) -> None:
    async def scenario():
        manager = MemoryManager(_store(tmp_path), ControlledUpdater(_plan()))
        manager.schedule(MemoryTurn("session", "user", "answer", NOW))
        assert "concise" not in manager.prompt_view().content
        diagnostics = await manager.await_pending()
        return manager, diagnostics

    manager, diagnostics = asyncio.run(scenario())
    assert diagnostics == ()
    assert "prefers concise output" in manager.prompt_view().content


def test_failure_warns_once_keeps_old_view_and_does_not_retry(tmp_path: Path) -> None:
    async def scenario():
        updater = ControlledUpdater(fail=True)
        manager = MemoryManager(_store(tmp_path), updater)
        old = manager.prompt_view()
        manager.schedule(MemoryTurn("session", "user", "answer", NOW))
        first = await manager.await_pending()
        second = await manager.await_pending()
        return updater, manager, old, first, second

    updater, manager, old, first, second = asyncio.run(scenario())
    assert updater.calls == 1
    assert manager.prompt_view() == old
    assert len(first) == 1 and first[0].code == "memory_update_failed"
    assert second == ()


def test_await_and_close_wait_for_the_same_background_task(tmp_path: Path) -> None:
    async def scenario():
        release = asyncio.Event()
        updater = ControlledUpdater(release=release)
        updater.started = asyncio.Event()
        manager = MemoryManager(_store(tmp_path), updater)
        manager.schedule(MemoryTurn("session", "user", "answer", NOW))
        await updater.started.wait()
        waiter = asyncio.create_task(manager.close())
        await asyncio.sleep(0)
        assert not waiter.done()
        release.set()
        return await waiter, updater.calls

    diagnostics, calls = asyncio.run(scenario())
    assert diagnostics == ()
    assert calls == 1
