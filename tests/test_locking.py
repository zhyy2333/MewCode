from pathlib import Path

from mewcode.locking import FileLock


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
