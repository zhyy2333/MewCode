from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from .lifecycle import WorktreeLifecycleService
from .models import (
    CleanupDiagnostic,
    CleanupReport,
    DEFAULT_CLEANUP_AGE,
    DEFAULT_CLEANUP_INTERVAL,
    MAX_CLEANUP_CANDIDATES,
)


class WorktreeJanitor:
    def __init__(
        self,
        lifecycle: WorktreeLifecycleService,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval: timedelta = DEFAULT_CLEANUP_INTERVAL,
        minimum_age: timedelta = DEFAULT_CLEANUP_AGE,
        candidate_limit: int = MAX_CLEANUP_CANDIDATES,
        scan_timeout_seconds: float = 30.0,
    ) -> None:
        if interval <= timedelta(0) or minimum_age < timedelta(0):
            raise ValueError("Worktree cleanup intervals are invalid.")
        if not 1 <= candidate_limit <= MAX_CLEANUP_CANDIDATES:
            raise ValueError("Worktree cleanup candidate limit is invalid.")
        if scan_timeout_seconds <= 0:
            raise ValueError("Worktree cleanup timeout must be positive.")
        self._lifecycle = lifecycle
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        self._interval = interval
        self._minimum_age = minimum_age
        self._candidate_limit = candidate_limit
        self._scan_timeout = scan_timeout_seconds
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        if self._closed or self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)

    async def scan_once(self) -> CleanupReport:
        if self._closed:
            return CleanupReport()
        try:
            return await asyncio.wait_for(
                self._lifecycle.cleanup_expired(
                    now=self._wall_clock(),
                    minimum_age=self._minimum_age,
                    limit=self._candidate_limit,
                ),
                timeout=self._scan_timeout,
            )
        except TimeoutError:
            return CleanupReport(0, 0, 0, (CleanupDiagnostic(None, "Worktree cleanup scan timed out."),))
        except Exception as exc:
            return CleanupReport(0, 0, 0, (CleanupDiagnostic(None, f"Worktree cleanup scan failed: {type(exc).__name__}."),))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        try:
            while not self._closed:
                await self.scan_once()
                await self._sleep(self._interval.total_seconds())
        except asyncio.CancelledError:
            pass
