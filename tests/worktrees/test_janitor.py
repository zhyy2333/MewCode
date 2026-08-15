from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from mewcode.worktrees import CleanupReport, WorktreeJanitor


class FakeLifecycle:
    def __init__(self) -> None:
        self.calls = []

    async def cleanup_expired(self, *, now, minimum_age, limit):
        self.calls.append((now, minimum_age, limit))
        return CleanupReport(1, 1, 0)


def test_scan_once_uses_injected_limits_and_clock() -> None:
    lifecycle = FakeLifecycle()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    janitor = WorktreeJanitor(lifecycle, wall_clock=lambda: now, minimum_age=timedelta(hours=24), candidate_limit=7)
    result = asyncio.run(janitor.scan_once())
    assert result.deleted == 1
    assert lifecycle.calls == [(now, timedelta(hours=24), 7)]


def test_start_is_nonblocking_and_close_is_idempotent() -> None:
    lifecycle = FakeLifecycle()
    gate = asyncio.Event()

    async def sleep(_seconds):
        await gate.wait()

    async def scenario() -> None:
        janitor = WorktreeJanitor(lifecycle, sleep=sleep)
        await janitor.start()
        await asyncio.sleep(0)
        assert lifecycle.calls
        await janitor.close()
        await janitor.close()

    asyncio.run(scenario())
