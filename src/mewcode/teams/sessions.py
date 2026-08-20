from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from mewcode.continuity.session_codec import decode_message, encode_message, valid_tool_prefix
from mewcode.locking import FileLock
from mewcode.providers import ChatMessage

from .models import MemberSessionState, TeamCorruptionError, TeamMemberRecord, TeamValidationError
from .paths import TeamPaths

SESSION_VERSION = 1


class MemberSessionBinding:
    def __init__(
        self,
        store: MemberSessionStore,
        member: TeamMemberRecord,
        path: Path,
        lock: FileLock,
        state: MemberSessionState,
    ) -> None:
        self._store = store
        self._member = member
        self._path = path
        self._lock = lock
        self._messages = state.messages
        self._delivered_ids = state.delivered_message_ids
        self.session_id = state.session_id
        self.context_archive_id = state.context_archive_id
        self._closed = False

    @property
    def delivered_inbound_ids(self) -> frozenset[str]:
        return self._delivered_ids

    def commit(self, messages: Sequence[ChatMessage]) -> None:
        self._ensure_open()
        candidate = tuple(messages)
        self._validate_boundary(candidate)
        if candidate == self._messages:
            return
        operation, payload = _history_delta(self._messages, candidate)
        self._append(
            _encode_record(
                "history",
                self._store.now(),
                operation=operation,
                messages=[encode_message(item) for item in payload],
            )
        )
        self._messages = candidate

    def commit_inbound(
        self,
        messages: Sequence[ChatMessage],
        inbound_ids: Sequence[str],
    ) -> None:
        self._ensure_open()
        candidate = tuple(messages)
        self._validate_boundary(candidate)
        ids = _validate_ids(inbound_ids)
        already = tuple(item for item in ids if item in self._delivered_ids)
        if already:
            if len(already) == len(ids) and candidate == self._messages:
                return
            raise TeamValidationError("Inbound delivery IDs must be committed as one batch.")
        if len(candidate) < len(self._messages) or candidate[: len(self._messages)] != self._messages:
            raise TeamValidationError("Inbound history must append to the member session.")
        payload = candidate[len(self._messages) :]
        if not payload or not ids:
            raise TeamValidationError("Inbound history requires messages and delivery IDs.")
        if len(payload) != len(ids):
            raise TeamValidationError("Inbound messages and delivery IDs do not match.")
        self._append(
            _encode_record(
                "inbound_history",
                self._store.now(),
                operation="append",
                messages=[encode_message(item) for item in payload],
                inbound_ids=list(ids),
            )
        )
        self._messages = candidate
        self._delivered_ids = self._delivered_ids.union(ids)

    def state(self) -> MemberSessionState:
        return MemberSessionState(
            self._member.member_id,
            self.session_id,
            self._messages,
            self._delivered_ids,
            self.context_archive_id,
            self._store.now(),
            len(self._messages),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lock.close()

    def _append(self, payload: bytes) -> None:
        try:
            with self._path.open("ab", buffering=0) as handle:
                view = memoryview(payload)
                while view:
                    written = os.write(handle.fileno(), view)
                    if written <= 0:
                        raise OSError("short member session write")
                    view = view[written:]
                os.fsync(handle.fileno())
        except OSError as exc:
            raise TeamCorruptionError("Unable to persist member session.") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise TeamValidationError("Member session is closed.")

    @staticmethod
    def _validate_boundary(messages: tuple[ChatMessage, ...]) -> None:
        if valid_tool_prefix(messages) != len(messages):
            raise TeamValidationError("Member session history ends inside an incomplete tool group.")


class MemberSessionStore:
    def __init__(
        self,
        paths: TeamPaths,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._paths = paths
        self._now = now

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TeamValidationError("Member session clock must be timezone-aware.")
        return value.astimezone(timezone.utc)

    def create(self, member: TeamMemberRecord) -> MemberSessionBinding:
        self._paths.ensure_directories()
        path = self._path(member)
        lock = self._acquire(member.member_id)
        try:
            if path.exists():
                raise TeamValidationError("Member session already exists.")
            session_id = f"team-member-{member.member_id}"
            archive_id = f"team-member-context-{member.member_id}"
            current = self.now()
            payload = _encode_record(
                "start",
                current,
                member_id=member.member_id,
                session_id=session_id,
                context_archive_id=archive_id,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            state = MemberSessionState(
                member.member_id, session_id, (), frozenset(), archive_id, current, 0
            )
            return MemberSessionBinding(self, member, path, lock, state)
        except BaseException:
            lock.close()
            raise

    def open(self, member: TeamMemberRecord) -> tuple[MemberSessionBinding, MemberSessionState]:
        path = self._path(member)
        lock = self._acquire(member.member_id)
        try:
            state = _replay(path, member.member_id)
            prefix = valid_tool_prefix(state.messages)
            valid_messages = state.messages[:prefix]
            recovered = MemberSessionState(
                state.member_id,
                state.session_id,
                valid_messages,
                state.delivered_message_ids,
                state.context_archive_id,
                state.last_activity,
                len(valid_messages),
            )
            binding = MemberSessionBinding(self, member, path, lock, state)
            if prefix != len(state.messages):
                binding.commit(valid_messages)
            return binding, recovered
        except BaseException:
            lock.close()
            raise

    def _path(self, member: TeamMemberRecord) -> Path:
        if member.session_name != f"{member.member_id}.jsonl":
            raise TeamValidationError("Member session filename does not match its identity.")
        return self._paths.member_session_file(member.member_id)

    def _acquire(self, member_id: str) -> FileLock:
        lock = FileLock(self._paths.member_lock(member_id))
        if not lock.acquire():
            raise TeamValidationError("Member session is already active.")
        return lock


def _replay(path: Path, member_id: str) -> MemberSessionState:
    if not path.exists():
        raise TeamValidationError("Member session does not exist.")
    messages: list[ChatMessage] = []
    delivered: set[str] = set()
    session_id: str | None = None
    archive_id: str | None = None
    last_activity: datetime | None = None
    valid_start = False
    try:
        with path.open("rb") as handle:
            while raw := handle.readline():
                if not raw.endswith(b"\n"):
                    break
                record = json.loads(raw.decode("utf-8"))
                if not isinstance(record, dict) or record.get("version") != SESSION_VERSION:
                    raise ValueError("invalid member session record")
                at = _parse_time(record.get("at"))
                record_type = record.get("type")
                if record_type == "start":
                    expected = {"version", "type", "at", "member_id", "session_id", "context_archive_id"}
                    if set(record) != expected or record.get("member_id") != member_id:
                        raise ValueError("member session identity mismatch")
                    session_id = _required_string(record.get("session_id"))
                    archive_id = _required_string(record.get("context_archive_id"))
                    valid_start = True
                elif record_type in {"history", "inbound_history"}:
                    required = {"version", "type", "at", "operation", "messages"}
                    if record_type == "inbound_history":
                        required.add("inbound_ids")
                    if set(record) != required:
                        raise ValueError("invalid member history shape")
                    decoded = tuple(decode_message(item) for item in _required_list(record.get("messages")))
                    operation = record.get("operation")
                    ids = _validate_ids(record.get("inbound_ids", ()))
                    if record_type == "inbound_history" and len(decoded) != len(ids):
                        raise ValueError("inbound messages and IDs do not match")
                    if operation == "append":
                        messages.extend(decoded)
                        delivered.update(ids)
                    elif operation == "replace":
                        messages = list(decoded)
                        if record_type == "inbound_history":
                            delivered = set(ids)
                    else:
                        raise ValueError("invalid member history operation")
                else:
                    raise ValueError("unknown member session record")
                last_activity = at
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise TeamCorruptionError("Member session is corrupt.") from exc
    if not valid_start or session_id is None or archive_id is None:
        raise TeamCorruptionError("Member session has no valid start record.")
    return MemberSessionState(
        member_id,
        session_id,
        tuple(messages),
        frozenset(delivered),
        archive_id,
        last_activity,
        valid_tool_prefix(messages),
    )


def _history_delta(previous: tuple[ChatMessage, ...], candidate: tuple[ChatMessage, ...]) -> tuple[str, tuple[ChatMessage, ...]]:
    if len(candidate) >= len(previous) and candidate[: len(previous)] == previous:
        return "append", candidate[len(previous) :]
    return "replace", candidate


def _validate_ids(value: Sequence[str] | object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("inbound IDs must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError("invalid inbound message ID")
    if len(set(result)) != len(result):
        raise ValueError("duplicate inbound message ID")
    return result


def _required_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("expected list")
    return value


def _required_string(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty string")
    return value


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid timestamp")
    return parsed.astimezone(timezone.utc)


def _encode_record(record_type: str, at: datetime, **payload: object) -> bytes:
    if at.tzinfo is None or at.utcoffset() is None:
        raise TeamValidationError("Member session timestamp must be timezone-aware.")
    record = {
        "version": SESSION_VERSION,
        "type": record_type,
        "at": at.astimezone(timezone.utc).isoformat(),
        **payload,
    }
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
