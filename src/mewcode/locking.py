from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


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
