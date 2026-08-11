from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Sequence
from uuid import uuid4

from mewcode.locking import FileLock
from mewcode.providers import ChatMessage
from mewcode.tools import ToolExecution

from .estimator import estimate_text_tokens
from .models import (
    ArchiveKind,
    ArchiveRecord,
    ContextArchiveError,
    ContextStatus,
    ContextStatusKind,
)


class ContextArchive:
    def __init__(
        self,
        workspace_root: Path,
        *,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._context_root = self._workspace_root / ".mewcode" / "context"
        self._session_id_factory = session_id_factory or (lambda: str(uuid4()))
        self._session_dir: Path | None = None
        self._lock: FileLock | None = None
        self._sequence = 0

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    def start(self) -> tuple[ContextStatus, ...]:
        if self._session_dir is not None:
            return ()
        warnings = list(self._cleanup_stale_sessions())
        self._context_root.mkdir(parents=True, exist_ok=True)
        session_dir = self._context_root / self._session_id_factory()
        session_dir.mkdir(parents=False, exist_ok=False)
        lock = FileLock(session_dir / ".active.lock")
        if not lock.acquire():
            shutil.rmtree(session_dir, ignore_errors=True)
            raise ContextArchiveError("Unable to lock the context session directory.")
        self._session_dir = session_dir
        self._lock = lock
        return tuple(warnings)

    def write_tool_result(self, execution: ToolExecution) -> ArchiveRecord:
        payload = {
            "version": 1,
            "kind": ArchiveKind.TOOL_RESULT.value,
            "execution": {
                "index": execution.index,
                "call_id": execution.request.id,
                "tool_name": execution.request.name,
                "arguments": execution.request.arguments,
                "raw_arguments": execution.request.raw_arguments,
                "result": {
                    "ok": execution.result.ok,
                    "tool_name": execution.result.tool_name,
                    "content": execution.result.content,
                    "error": execution.result.error,
                    "metadata": execution.result.metadata,
                },
            },
        }
        return self._write_record(ArchiveKind.TOOL_RESULT, "tool", payload)

    def write_history(self, messages: Sequence[ChatMessage]) -> ArchiveRecord:
        payload = {
            "version": 1,
            "kind": ArchiveKind.HISTORY.value,
            "messages": [
                {
                    "role": message.role,
                    "kind": message.kind.value if message.kind is not None else None,
                    "group_id": message.group_id,
                    "content": message.content,
                }
                for message in messages
            ],
        }
        return self._write_record(ArchiveKind.HISTORY, "history", payload)

    def discard(self, record: ArchiveRecord) -> ContextStatus | None:
        try:
            target = self._resolve_record(record)
            target.unlink(missing_ok=True)
        except OSError:
            return ContextStatus(
                ContextStatusKind.CLEANUP_WARNING,
                "An unused context archive could not be removed.",
            )
        return None

    def close(self) -> tuple[ContextStatus, ...]:
        session_dir = self._session_dir
        self._session_dir = None
        lock = self._lock
        self._lock = None
        if lock is not None:
            lock.close()
        if session_dir is None:
            return ()
        try:
            shutil.rmtree(session_dir)
        except OSError:
            return (
                ContextStatus(
                    ContextStatusKind.CLEANUP_WARNING,
                    "The context session directory could not be removed.",
                ),
            )
        return ()

    def _write_record(
        self,
        kind: ArchiveKind,
        prefix: str,
        payload: dict[str, Any],
    ) -> ArchiveRecord:
        session_dir = self._require_session()
        self._sequence += 1
        sequence = self._sequence
        filename = f"{prefix}-{sequence:06d}.json"
        target = session_dir / filename
        temporary = session_dir / f".{filename}.{uuid4().hex}.tmp"
        try:
            text = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, target)
        except (OSError, TypeError, ValueError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ContextArchiveError(
                f"Unable to archive {kind.value}."
            ) from exc
        relative = target.relative_to(self._workspace_root).as_posix()
        return ArchiveRecord(kind, relative, estimate_text_tokens(text), sequence)

    def _cleanup_stale_sessions(self) -> tuple[ContextStatus, ...]:
        if not self._context_root.exists():
            return ()
        warnings: list[ContextStatus] = []
        for candidate in sorted(self._context_root.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            lock_path = candidate / ".active.lock"
            probe: FileLock | None = None
            try:
                probe = FileLock(lock_path)
                if not probe.acquire():
                    probe.close()
                    continue
                probe.close()
                shutil.rmtree(candidate)
            except OSError:
                if probe is not None:
                    try:
                        probe.close()
                    except OSError:
                        pass
                warnings.append(
                    ContextStatus(
                        ContextStatusKind.CLEANUP_WARNING,
                        "A stale context session could not be removed.",
                    )
                )
        return tuple(warnings)

    def _require_session(self) -> Path:
        if self._session_dir is None:
            raise ContextArchiveError("The context archive has not been started.")
        return self._session_dir

    def _resolve_record(self, record: ArchiveRecord) -> Path:
        target = (self._workspace_root / record.relative_path).resolve()
        session_dir = self._require_session().resolve()
        if target.parent != session_dir:
            raise ContextArchiveError("Archive record is outside the active session.")
        return target
