from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Protocol
import uuid

from mewcode.locking import RetryingFileLock

from .codec import decode_mailbox_record, encode_mailbox_record
from .models import (
    BroadcastResult,
    DeliveryResult,
    MailboxMessageRecord,
    MailboxPage,
    MailboxReadRecord,
    OutboxFlushResult,
    TeamActor,
    TeamCorruptionError,
    TeamMemberStatus,
    TeamMessage,
    TeamMessageDraft,
    TeamName,
    TeamProtocol,
    TeamState,
    TeamValidationError,
)
from .paths import TeamPaths
from .protocols import TeamProtocolRouter
from .repository import TeamMutationRunner, TeamRepository


class MemberWakeSink(Protocol):
    async def request_wake(self, member_id: str, *, message_ids: Sequence[str]) -> None: ...


class TeamMailboxStore:
    def __init__(
        self,
        paths: TeamPaths,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        lock_retry_seconds: float = 5.0,
    ) -> None:
        self._paths = paths
        self._now = now
        self._new_id = new_id
        self._lock_retry_seconds = lock_retry_seconds

    async def append_message(self, participant_id: str, message: TeamMessage) -> bool:
        async with self._lock(participant_id):
            messages = self.messages(participant_id)
            if any(item.message_id == message.message_id for item in messages):
                return False
            self._append(self._paths.mailbox_file(participant_id), encode_mailbox_record(MailboxMessageRecord(message)))
            return True

    async def append_read(self, participant_id: str, message_ids: Sequence[str]) -> tuple[str, ...]:
        async with self._lock(participant_id):
            known = {item.message_id for item in self.messages(participant_id)}
            selected = tuple(dict.fromkeys(item for item in message_ids if item in known))
            if not selected:
                return ()
            self._append(
                self._paths.mailbox_file(participant_id),
                encode_mailbox_record(MailboxReadRecord(self._new_id(), selected, self._now())),
            )
        return selected

    def messages(self, participant_id: str) -> tuple[TeamMessage, ...]:
        path = self._paths.mailbox_file(participant_id)
        if not path.exists():
            return ()
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise TeamCorruptionError("Unable to read team mailbox.") from exc
        records = []
        lines = payload.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if not line.endswith((b"\n", b"\r")):
                if index == len(lines) - 1:
                    break
                raise TeamCorruptionError("Mailbox contains an incomplete middle record.")
            records.append(decode_mailbox_record(line))
        messages: list[TeamMessage] = []
        seen: set[str] = set()
        read: set[str] = set()
        for record in records:
            if isinstance(record, MailboxMessageRecord):
                if record.message.message_id not in seen:
                    messages.append(record.message)
                    seen.add(record.message.message_id)
            else:
                read.update(record.message_ids)
        return tuple(replace(message, read=message.message_id in read) for message in messages)

    def _lock(self, participant_id: str) -> RetryingFileLock:
        return RetryingFileLock(
            self._paths.mailbox_lock(participant_id),
            token=self._new_id(),
            holder=participant_id,
            retry_seconds=self._lock_retry_seconds,
            now=self._now,
        )

    @staticmethod
    def _append(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())


class TeamMailboxService:
    def __init__(
        self,
        repository: TeamRepository,
        team: TeamName,
        router: TeamProtocolRouter,
        *,
        lease_fence: Callable[[], tuple[str, int]],
        wake_sink: MemberWakeSink | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        lock_retry_seconds: float = 5.0,
    ) -> None:
        self._repository = repository
        self._team = team
        self._router = router
        self._lease_fence = lease_fence
        self._wake_sink = wake_sink
        self._now = now
        self._new_id = new_id
        self._store = TeamMailboxStore(
            repository.paths(team), now=now, new_id=new_id,
            lock_retry_seconds=lock_retry_seconds,
        )
        self._mutations = TeamMutationRunner(repository)

    def set_wake_sink(self, wake_sink: MemberWakeSink | None) -> None:
        self._wake_sink = wake_sink

    async def send(
        self,
        actor: TeamActor,
        *,
        recipient: str,
        summary: str,
        body: str,
        protocol: TeamProtocol,
        payload: Mapping[str, object],
        message_id: str | None = None,
        correlation_id: str | None = None,
    ) -> DeliveryResult:
        transition = await self._router.prepare(
            actor,
            TeamMessageDraft(
                recipient=recipient,
                summary=summary,
                body=body,
                protocol=protocol,
                payload=payload,
                message_id=message_id,
                correlation_id=correlation_id,
            ),
        )
        expected = transition.candidate_state.revision
        self._repository.compare_and_swap(
            self._team,
            expected_revision=expected,
            lease_fence=actor.lease_fence,
            candidate=transition.candidate_state,
        )
        await self._router.committed(transition)
        flushed = await self.flush_outbox()
        delivered = transition.message.message_id in flushed.delivered_ids
        return DeliveryResult(
            transition.message.recipient_id,
            transition.message.message_id,
            delivered,
            None if delivered else "Message is safely queued for retry.",
            transition.safe_pause,
        )

    async def broadcast(
        self,
        actor: TeamActor,
        *,
        summary: str,
        body: str,
        protocol: TeamProtocol,
        payload: Mapping[str, object],
        correlation_id: str | None = None,
    ) -> BroadcastResult:
        state = self._repository.load(self._team)
        correlation = correlation_id or self._new_id()
        targets = [
            item for item in state.registry.values()
            if item.participant_id != actor.participant_id
        ]
        results: list[DeliveryResult] = []
        for target in targets:
            digest = hashlib.sha256(f"{correlation}\x00{target.participant_id}".encode()).hexdigest()[:32]
            try:
                result = await self.send(
                    actor,
                    recipient=target.participant_name.value,
                    summary=summary,
                    body=body,
                    protocol=protocol,
                    payload=payload,
                    message_id=digest,
                    correlation_id=correlation,
                )
            except Exception as exc:
                result = DeliveryResult(target.participant_id, digest, False, type(exc).__name__)
            results.append(result)
        return BroadcastResult(correlation, tuple(results))

    def list(
        self,
        actor: TeamActor,
        *,
        unread_only: bool = True,
        limit: int = 100,
        cursor: str | None = None,
    ) -> MailboxPage:
        if limit < 1 or limit > 1000:
            raise TeamValidationError("Mailbox page limit is invalid.")
        self._registration(self._repository.load(self._team), actor.participant_id)
        messages = self._store.messages(actor.participant_id)
        if unread_only:
            messages = tuple(item for item in messages if not item.read)
        start = int(cursor) if cursor is not None else 0
        if start < 0 or start > len(messages):
            raise TeamValidationError("Mailbox cursor is invalid.")
        page = messages[start:start + limit]
        next_cursor = str(start + limit) if start + limit < len(messages) else None
        return MailboxPage(page, next_cursor)

    async def mark_read(self, actor: TeamActor, message_ids: Sequence[str]) -> tuple[str, ...]:
        self._registration(self._repository.load(self._team), actor.participant_id)
        return await self._store.append_read(actor.participant_id, message_ids)

    async def flush_outbox(self) -> OutboxFlushResult:
        delivered: list[str] = []
        failed: list[str] = []
        state = self._repository.load(self._team)
        for entry in tuple(item for item in state.outbox if not item.delivered):
            try:
                await self._store.append_message(entry.message.recipient_id, entry.message)
                self._mark_delivered(entry.outbox_id)
                delivered.append(entry.message.message_id)
                await self._wake_if_needed(entry.message)
            except Exception:
                failed.append(entry.message.message_id)
        return OutboxFlushResult(tuple(delivered), tuple(failed))

    def _mark_delivered(self, outbox_id: str) -> None:
        now = self._now()

        def transform(state: TeamState) -> TeamState:
            outbox = tuple(
                replace(item, delivered=True, delivered_at=now, last_error=None)
                if item.outbox_id == outbox_id else item
                for item in state.outbox
            )
            return replace(state, outbox=outbox, updated_at=now)

        self._mutations.run(self._team, lease_fence=self._lease_fence(), transform=transform)

    async def _wake_if_needed(self, message: TeamMessage) -> None:
        if self._wake_sink is None:
            return
        state = self._repository.load(self._team)
        member = state.members.get(message.recipient_id)
        if member is None or member.status not in {
            TeamMemberStatus.IDLE,
            TeamMemberStatus.INTERRUPTED,
            TeamMemberStatus.FAILED,
        }:
            return
        await self._wake_sink.request_wake(member.member_id, message_ids=(message.message_id,))

    @staticmethod
    def _registration(state: TeamState, participant_id: str):
        for item in state.registry.values():
            if item.participant_id == participant_id:
                return item
        raise TeamValidationError("Participant is not registered in this team.")
