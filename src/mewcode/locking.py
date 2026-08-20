from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Awaitable, BinaryIO, Callable


class FileLock:
    """Small cross-platform advisory lock backed by a dedicated file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None
        self._locked = False

    @property
    def locked(self) -> bool:
        return self._locked

    def acquire(self) -> bool:
        if self._locked:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        self._locked = True
        return True

    def release(self) -> None:
        handle = self._handle
        if not self._locked or handle is None:
            return
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._locked = False

    def close(self) -> None:
        handle = self._handle
        try:
            self.release()
        finally:
            self._handle = None
            if handle is not None:
                handle.close()

    def __enter__(self) -> FileLock:
        if not self.acquire():
            raise OSError(f"Unable to acquire lock: {self._path.name}")
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass(frozen=True)
class LockMetadata:
    token: str
    holder: str
    created_at: datetime


class RetryingFileLock:
    """Advisory lock with bounded retry and diagnostic metadata."""

    def __init__(
        self,
        path: Path,
        *,
        token: str,
        holder: str,
        retry_seconds: float = 5.0,
        stale_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        lock_factory: Callable[[Path], FileLock] = FileLock,
    ) -> None:
        if retry_seconds < 0 or stale_seconds <= 0:
            raise ValueError("Lock retry and stale durations are invalid.")
        self._path = Path(path)
        self._metadata = LockMetadata(token, holder, now())
        self._retry_seconds = retry_seconds
        self._stale_seconds = stale_seconds
        self._monotonic = monotonic
        self._now = now
        self._sleep = sleep
        self._lock = lock_factory(self._path)

    @property
    def locked(self) -> bool:
        return self._lock.locked

    async def acquire(self) -> bool:
        deadline = self._monotonic() + self._retry_seconds
        while True:
            if self._lock.acquire():
                self._write_metadata()
                return True
            if self._monotonic() >= deadline:
                return False
            await self._sleep(min(0.05, max(0.0, deadline - self._monotonic())))

    def release(self) -> None:
        self._lock.close()

    def metadata_age_seconds(self) -> float | None:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(value["created_at"])
            if created.tzinfo is None or created.utcoffset() is None:
                return None
            return max(0.0, (self._now() - created.astimezone(timezone.utc)).total_seconds())
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @property
    def metadata_is_stale(self) -> bool:
        age = self.metadata_age_seconds()
        return age is not None and age > self._stale_seconds

    def _write_metadata(self) -> None:
        handle = self._lock._handle
        if handle is None:  # pragma: no cover - guarded by acquire
            raise RuntimeError("Cannot write metadata without an active lock.")
        payload = json.dumps(
            {
                "token": self._metadata.token,
                "holder": self._metadata.holder,
                "created_at": self._metadata.created_at.astimezone(timezone.utc).isoformat(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        handle.seek(0)
        handle.truncate()
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(0)

    async def __aenter__(self) -> RetryingFileLock:
        if not await self.acquire():
            raise TimeoutError(
                f"Unable to acquire lock within {self._retry_seconds:g} seconds: {self._path.name}"
            )
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.release()
