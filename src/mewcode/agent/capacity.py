from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from uuid import uuid4


class AgentCapacityError(RuntimeError):
    """Base error for shared agent-capacity coordination."""


class AgentCapacityClosedError(AgentCapacityError):
    pass


@dataclass
class _Waiter:
    owner: tuple[str, str]
    future: asyncio.Future[AgentCapacityLease]


class AgentCapacityLease:
    def __init__(
        self,
        pool: AgentCapacityPool,
        owner_kind: str,
        owner_id: str,
        token: str,
    ) -> None:
        self._pool = pool
        self.owner_kind = owner_kind
        self.owner_id = owner_id
        self._token = token
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._pool._release((self.owner_kind, self.owner_id), self._token)

    async def __aenter__(self) -> AgentCapacityLease:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()


class AgentCapacityPool:
    """A process-local FIFO capacity pool shared by all agent runtimes."""

    def __init__(self, limit: int = 8) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self.limit = limit
        self._lock = asyncio.Lock()
        self._active: dict[tuple[str, str], str] = {}
        self._waiters: deque[_Waiter] = deque()
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def waiting_count(self) -> int:
        return len(self._waiters)

    async def try_acquire(
        self,
        owner_kind: str,
        owner_id: str,
    ) -> AgentCapacityLease | None:
        owner = self._validate_owner(owner_kind, owner_id)
        async with self._lock:
            self._ensure_open()
            self._ensure_unique(owner)
            if len(self._active) >= self.limit or self._waiters:
                return None
            return self._grant(owner)

    async def acquire(self, owner_kind: str, owner_id: str) -> AgentCapacityLease:
        owner = self._validate_owner(owner_kind, owner_id)
        async with self._lock:
            self._ensure_open()
            self._ensure_unique(owner)
            if len(self._active) < self.limit and not self._waiters:
                return self._grant(owner)
            future: asyncio.Future[AgentCapacityLease] = (
                asyncio.get_running_loop().create_future()
            )
            waiter = _Waiter(owner, future)
            self._waiters.append(waiter)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            granted: AgentCapacityLease | None = None
            async with self._lock:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    if future.done() and not future.cancelled():
                        try:
                            granted = future.result()
                        except AgentCapacityClosedError:
                            pass
            if granted is not None:
                await granted.close()
            raise

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            waiters = tuple(self._waiters)
            self._waiters.clear()
            for waiter in waiters:
                if not waiter.future.done():
                    waiter.future.set_exception(
                        AgentCapacityClosedError("The agent capacity pool is closed.")
                    )

    async def _release(self, owner: tuple[str, str], token: str) -> None:
        async with self._lock:
            if self._active.get(owner) != token:
                return
            del self._active[owner]
            if not self._closed:
                self._grant_waiters()

    def _grant_waiters(self) -> None:
        while self._waiters and len(self._active) < self.limit:
            waiter = self._waiters.popleft()
            if waiter.future.done():
                continue
            lease = self._grant(waiter.owner)
            waiter.future.set_result(lease)

    def _grant(self, owner: tuple[str, str]) -> AgentCapacityLease:
        token = str(uuid4())
        self._active[owner] = token
        return AgentCapacityLease(self, owner[0], owner[1], token)

    def _ensure_open(self) -> None:
        if self._closed:
            raise AgentCapacityClosedError("The agent capacity pool is closed.")

    def _ensure_unique(self, owner: tuple[str, str]) -> None:
        if owner in self._active or any(item.owner == owner for item in self._waiters):
            raise AgentCapacityError("This agent-capacity owner is already active.")

    @staticmethod
    def _validate_owner(owner_kind: str, owner_id: str) -> tuple[str, str]:
        if not isinstance(owner_kind, str) or not owner_kind.strip():
            raise ValueError("owner_kind must not be empty")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id must not be empty")
        return owner_kind.strip(), owner_id.strip()
