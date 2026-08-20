from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import asyncio
import uuid

from mewcode.locking import FileLock

from .codec import decode_lead_lease, encode_lead_lease
from .models import (
    SCHEMA_VERSION,
    TeamLeadLease,
    TeamLeadLeaseRecord,
    TeamLeaseError,
    TeamName,
)
from .paths import TeamPaths
from .repository import TeamRepository, atomic_write


LEASE_HEARTBEAT_SECONDS = 10.0
LEASE_EXPIRY_SECONDS = 60.0


class TeamLeaseService:
    def __init__(
        self,
        repository: TeamRepository,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repository = repository
        self._now = now
        self._new_id = new_id
        self._sleep = sleep

    async def acquire(
        self,
        team: TeamName,
        *,
        root_session_id: str,
        process_id: str,
    ) -> TeamLeadLease:
        state = self._repository.load(team)
        paths = self._repository.paths(team)
        paths.ensure_directories()
        lock = self._lock(paths)
        try:
            previous = self._read(paths)
            if previous is not None and not self._expired(previous):
                raise TeamLeaseError("Team already has an active Lead.")
            previous_payload = paths.lease_file.read_bytes() if paths.lease_file.exists() else None
            await self._sleep(0)
            confirm_payload = paths.lease_file.read_bytes() if paths.lease_file.exists() else None
            if confirm_payload != previous_payload:
                raise TeamLeaseError("Lead lease changed while confirming takeover.")
            generation = 1 if previous is None else previous.generation + 1
            record = TeamLeadLeaseRecord(
                schema_version=SCHEMA_VERSION,
                team_id=state.manifest.team_id,
                lease_id=self._new_id(),
                generation=generation,
                holder_session_id=root_session_id,
                holder_process_id=process_id,
                heartbeat_at=self._now(),
            )
            atomic_write(paths.lease_file, encode_lead_lease(record))
            return TeamLeadLease(record)
        finally:
            lock.close()

    async def renew(self, lease: TeamLeadLease) -> TeamLeadLease:
        paths = self._paths_for(lease)
        lock = self._lock(paths)
        try:
            current = self._require_current(paths, lease)
            if self._expired(current):
                raise TeamLeaseError("Lead lease expired before renewal.")
            renewed = replace(current, heartbeat_at=self._now())
            atomic_write(paths.lease_file, encode_lead_lease(renewed))
            return TeamLeadLease(renewed)
        finally:
            lock.close()

    async def validate(self, lease: TeamLeadLease) -> None:
        if lease.released:
            raise TeamLeaseError("Lead lease has been released.")
        current = self._require_current(self._paths_for(lease), lease)
        if self._expired(current):
            raise TeamLeaseError("Lead lease has expired.")

    async def release(self, lease: TeamLeadLease) -> None:
        paths = self._paths_for(lease)
        lock = self._lock(paths)
        try:
            current = self._read(paths)
            if current is None:
                return
            if (current.lease_id, current.generation) != lease.fence:
                return
            released = replace(current, heartbeat_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
            atomic_write(paths.lease_file, encode_lead_lease(released))
        finally:
            lock.close()

    def _paths_for(self, lease: TeamLeadLease) -> TeamPaths:
        for summary in self._repository.list():
            if summary.team_id == lease.record.team_id:
                from .paths import TeamNamePolicy
                return self._repository.paths(TeamNamePolicy().parse(summary.name))
        raise TeamLeaseError("Lease team no longer exists.")

    def _lock(self, paths: TeamPaths) -> FileLock:
        lock = FileLock(paths.lease_lock)
        if not lock.acquire():
            raise TeamLeaseError("Lead lease is busy.")
        return lock

    @staticmethod
    def _read(paths: TeamPaths) -> TeamLeadLeaseRecord | None:
        try:
            return decode_lead_lease(paths.lease_file.read_bytes())
        except FileNotFoundError:
            return None

    def _require_current(self, paths: TeamPaths, lease: TeamLeadLease) -> TeamLeadLeaseRecord:
        current = self._read(paths)
        if current is None or current.team_id != lease.record.team_id:
            raise TeamLeaseError("Lead lease is missing.")
        if (current.lease_id, current.generation) != lease.fence:
            raise TeamLeaseError("Lead lease fence is stale.")
        return current

    def _expired(self, record: TeamLeadLeaseRecord) -> bool:
        return self._now() - record.heartbeat_at >= timedelta(seconds=LEASE_EXPIRY_SECONDS)
