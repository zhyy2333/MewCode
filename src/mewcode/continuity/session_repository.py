from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import secrets

from mewcode.locking import FileLock
from mewcode.providers import ChatMessage, MessageKind

from .diagnostics import (
    ContinuityComponent,
    ContinuityDiagnostic,
    DiagnosticSeverity,
    SessionError,
    SessionPersistenceError,
)
from .paths import ContinuityPaths
from .session_codec import (
    encode_history,
    encode_plan,
    encode_start,
    replay_file,
    session_title,
    valid_tool_prefix,
)
from .session_models import (
    SessionOpenMode,
    SessionOpenRequest,
    SessionOpenResult,
    SessionState,
    SessionSummary,
    StoredPlan,
)

SESSION_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
SESSION_RETENTION = timedelta(days=30)
GAP_THRESHOLD = timedelta(hours=24)
MAINTENANCE_INTERVAL = timedelta(hours=24)


class SessionBinding:
    def __init__(
        self,
        repository: SessionRepository,
        session_id: str,
        path: Path,
        lock: FileLock,
        messages: Sequence[ChatMessage],
        pending_plan: StoredPlan | None,
    ) -> None:
        self._repository = repository
        self.session_id = session_id
        self._path = path
        self._lock = lock
        self._messages = tuple(messages)
        self._pending_plan = pending_plan
        self._closed = False

    def maintain(self, now: datetime) -> tuple[ContinuityDiagnostic, ...]:
        return self._repository.maintain(now)

    def commit_history(
        self,
        messages: Sequence[ChatMessage],
        *,
        now: datetime | None = None,
    ) -> None:
        self._ensure_open()
        candidate = tuple(messages)
        if candidate == self._messages:
            return
        if len(candidate) > len(self._messages) and candidate[: len(self._messages)] == self._messages:
            operation = "append"
            payload = candidate[len(self._messages) :]
        else:
            operation = "replace"
            payload = candidate
        self._append_record(encode_history(payload, operation, now or self._repository.now()))
        self._messages = candidate

    def commit_plan(
        self,
        pending_plan: StoredPlan | None,
        *,
        now: datetime | None = None,
    ) -> None:
        self._ensure_open()
        if pending_plan == self._pending_plan:
            return
        self._append_record(encode_plan(pending_plan, now or self._repository.now()))
        self._pending_plan = pending_plan

    def close(self) -> tuple[ContinuityDiagnostic, ...]:
        if self._closed:
            return ()
        self._closed = True
        self._lock.close()
        return ()

    def _append_record(self, payload: bytes) -> None:
        try:
            with self._path.open("ab", buffering=0) as handle:
                view = memoryview(payload)
                while view:
                    written = os.write(handle.fileno(), view)
                    if written <= 0:
                        raise OSError("short session write")
                    view = view[written:]
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SessionPersistenceError("The current session could not be persisted.") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise SessionPersistenceError("The current session is closed.")


class SessionRepository:
    def __init__(
        self,
        paths: ContinuityPaths,
        *,
        clock: Callable[[], datetime] | None = None,
        suffix_factory: Callable[[], str] | None = None,
    ) -> None:
        self._paths = paths
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._suffix_factory = suffix_factory or (lambda: secrets.token_hex(2))
        self._last_maintenance: datetime | None = None

    def now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SessionError("Session clock must return a timezone-aware datetime.")
        return value

    def scan(self, now: datetime | None = None) -> tuple[SessionSummary, ...]:
        current = now or self.now()
        root = self._paths.sessions_root
        if not root.exists():
            return ()
        summaries: list[SessionSummary] = []
        for path in sorted(root.glob("*.jsonl"), key=lambda item: item.name):
            session_id = path.stem
            if not SESSION_ID_PATTERN.fullmatch(session_id):
                continue
            try:
                replay = replay_file(path, session_id)
            except OSError:
                continue
            last = replay.last_activity or _mtime(path)
            summaries.append(
                SessionSummary(
                    session_id,
                    session_title(replay.messages, session_id),
                    len(replay.messages),
                    last,
                    replay.recoverable and current - last <= SESSION_RETENTION,
                    replay.invalid_lines,
                )
            )
        return tuple(summaries)

    def open(
        self,
        request: SessionOpenRequest = SessionOpenRequest(),
        now: datetime | None = None,
    ) -> SessionOpenResult:
        current = now or self.now()
        self._paths.sessions_root.mkdir(parents=True, exist_ok=True)
        (self._paths.sessions_root / ".locks").mkdir(parents=True, exist_ok=True)
        if request.mode is SessionOpenMode.NEW:
            return self._create(current)
        if request.mode is SessionOpenMode.RESUME:
            assert request.session_id is not None
            return self._open_existing(request.session_id, current, explicit=True)

        diagnostics: list[ContinuityDiagnostic] = []
        candidates = sorted(
            self.scan(current),
            key=lambda item: (item.last_activity, item.session_id),
            reverse=True,
        )
        for candidate in candidates:
            if not candidate.recoverable:
                continue
            try:
                result = self._open_existing(candidate.session_id, current, explicit=False)
                return SessionOpenResult(
                    result.binding,
                    result.state,
                    tuple([*diagnostics, *result.diagnostics]),
                )
            except SessionError:
                diagnostics.append(_diagnostic("candidate_skipped", "A recent session could not be recovered."))
        created = self._create(current)
        return SessionOpenResult(created.binding, created.state, tuple([*diagnostics, *created.diagnostics]))

    def maintain(self, now: datetime | None = None) -> tuple[ContinuityDiagnostic, ...]:
        current = now or self.now()
        if (
            self._last_maintenance is not None
            and current - self._last_maintenance < MAINTENANCE_INTERVAL
        ):
            return ()
        self._last_maintenance = current
        diagnostics: list[ContinuityDiagnostic] = []
        root = self._paths.sessions_root
        if not root.exists():
            return ()
        for path in sorted(root.glob("*.jsonl"), key=lambda item: item.name):
            session_id = path.stem
            if not SESSION_ID_PATTERN.fullmatch(session_id):
                continue
            try:
                replay = replay_file(path, session_id)
                last = replay.last_activity or _mtime(path)
                if current - last <= SESSION_RETENTION:
                    continue
                lock = FileLock(self._lock_path(session_id))
                if not lock.acquire():
                    lock.close()
                    continue
                try:
                    path.unlink(missing_ok=True)
                finally:
                    lock.close()
                try:
                    self._lock_path(session_id).unlink(missing_ok=True)
                except OSError:
                    pass
            except OSError:
                diagnostics.append(_diagnostic("cleanup_failed", "An expired session could not be removed."))
        return tuple(diagnostics)

    def _create(self, now: datetime) -> SessionOpenResult:
        for _ in range(256):
            suffix = self._suffix_factory().casefold()
            if not re.fullmatch(r"[0-9a-f]{4}", suffix):
                raise SessionError("Session suffix factory returned an invalid value.")
            session_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{suffix}"
            path = self._paths.sessions_root / f"{session_id}.jsonl"
            lock = FileLock(self._lock_path(session_id))
            if not lock.acquire():
                lock.close()
                continue
            try:
                with path.open("xb", buffering=0) as handle:
                    payload = encode_start(session_id, now)
                    os.write(handle.fileno(), payload)
                    os.fsync(handle.fileno())
            except FileExistsError:
                lock.close()
                continue
            except OSError as exc:
                lock.close()
                raise SessionError("A new session could not be created.") from exc
            binding = SessionBinding(self, session_id, path, lock, (), None)
            return SessionOpenResult(
                binding,
                SessionState(session_id, (), None, now),
                (_diagnostic("created", f"Created session {session_id}."),),
            )
        raise SessionError("A unique session id could not be allocated.")

    def _open_existing(
        self,
        session_id: str,
        now: datetime,
        *,
        explicit: bool,
    ) -> SessionOpenResult:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionError("The requested session id is invalid.")
        path = self._paths.sessions_root / f"{session_id}.jsonl"
        if not path.is_file():
            raise SessionError("The requested session does not exist.")
        lock = FileLock(self._lock_path(session_id))
        if not lock.acquire():
            lock.close()
            raise SessionError("The requested session is already active.")
        diagnostics: list[ContinuityDiagnostic] = []
        try:
            replay = replay_file(path, session_id)
            if not replay.recoverable:
                raise SessionError("The requested session could not be recovered.")
            assert replay.last_activity is not None
            if now - replay.last_activity > SESSION_RETENTION:
                raise SessionError("The requested session has expired.")
            if replay.partial_offset is not None:
                with path.open("r+b") as handle:
                    handle.truncate(replay.partial_offset)
                    handle.flush()
                    os.fsync(handle.fileno())
                diagnostics.append(_diagnostic("bad_lines_skipped", "Invalid session records were skipped."))
            elif replay.invalid_lines:
                diagnostics.append(_diagnostic("bad_lines_skipped", "Invalid session records were skipped."))
            prefix = valid_tool_prefix(replay.messages)
            valid_messages = replay.messages[:prefix]
            binding = SessionBinding(
                self,
                session_id,
                path,
                lock,
                replay.messages,
                replay.pending_plan,
            )
            if prefix != len(replay.messages):
                binding.commit_history(valid_messages, now=now)
                diagnostics.append(_diagnostic("history_repaired", "Incomplete tool history was removed during recovery."))
            if now - replay.last_activity > GAP_THRESHOLD:
                notice = ChatMessage(
                    "system",
                    (
                        "Session resumed after a long pause. "
                        f"Last activity: {replay.last_activity.isoformat()}. "
                        f"Resumed at: {now.isoformat()}."
                    ),
                    MessageKind.RESUME_NOTICE,
                )
                valid_messages = (*valid_messages, notice)
                binding.commit_history(valid_messages, now=now)
                diagnostics.append(_diagnostic("time_gap", "A session time-gap reminder was added."))
            diagnostics.append(_diagnostic("resumed", f"Resumed session {session_id}."))
            return SessionOpenResult(
                binding,
                SessionState(session_id, tuple(valid_messages), replay.pending_plan, now),
                tuple(diagnostics),
            )
        except BaseException:
            lock.close()
            raise

    def _lock_path(self, session_id: str) -> Path:
        return self._paths.sessions_root / ".locks" / f"{session_id}.lock"


def _diagnostic(code: str, message: str) -> ContinuityDiagnostic:
    return ContinuityDiagnostic(
        ContinuityComponent.SESSION,
        code,
        DiagnosticSeverity.INFO if code in {"created", "resumed", "time_gap"} else DiagnosticSeverity.WARNING,
        message,
    )


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
