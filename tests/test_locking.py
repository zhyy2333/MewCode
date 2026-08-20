from pathlib import Path

import asyncio
from datetime import datetime, timezone

from mewcode.locking import FileLock, RetryingFileLock


def test_file_lock_rejects_competitor_and_releases(tmp_path: Path) -> None:
    path = tmp_path / "locks" / "active.lock"
    first = FileLock(path)
    second = FileLock(path)
    assert first.acquire() is True
    assert first.acquire() is True
    assert second.acquire() is False
    first.close()
    assert second.acquire() is True
    second.close()
    second.close()


def test_file_lock_context_manager(tmp_path: Path) -> None:
    with FileLock(tmp_path / "active.lock") as lock:
        assert lock.locked
    assert lock.locked is False


def test_retrying_lock_writes_metadata_and_times_out_competitor(tmp_path: Path) -> None:
    path = tmp_path / "retry.lock"
    first = RetryingFileLock(path, token="one", holder="first", retry_seconds=0)
    second = RetryingFileLock(path, token="two", holder="second", retry_seconds=0)

    async def scenario() -> None:
        assert await first.acquire() is True
        assert await second.acquire() is False
        first.release()
        assert await second.acquire() is True
        second.release()

    asyncio.run(scenario())


def test_retrying_lock_reports_stale_metadata_without_stealing_active_lock(tmp_path: Path) -> None:
    path = tmp_path / "stale.lock"
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    current = datetime(2020, 1, 1, 0, 1, tzinfo=timezone.utc)
    first = RetryingFileLock(path, token="one", holder="first", retry_seconds=0, now=lambda: old)
    second = RetryingFileLock(path, token="two", holder="second", retry_seconds=0, now=lambda: current)

    async def scenario() -> None:
        assert await first.acquire() is True
        assert await second.acquire() is False
        first.release()
        assert second.metadata_is_stale is True
        assert await second.acquire() is True
        second.release()

    asyncio.run(scenario())
