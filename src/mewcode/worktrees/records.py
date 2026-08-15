from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Iterable

from .models import (
    RepositoryIdentity,
    WorktreeLayout,
    WorktreeMarker,
    WorktreeRecord,
    WorktreeState,
    WorktreeValidationError,
)
from .paths import is_link_or_reparse


_RECORD_FIELDS = {
    "schema_version", "management_id", "repository_id", "name", "canonical_key",
    "root", "branch_ref", "base_oid", "git_hooks_path", "task_id", "state",
    "created_at", "last_used_at", "retained_reason",
}
_MARKER_FIELDS = {
    "schema_version", "management_id", "repository_id", "name", "branch_ref",
    "base_oid", "git_hooks_path", "task_id", "ready",
}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorktreeValidationError("Managed JSON contains a duplicate field.")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if is_link_or_reparse(path) or not path.is_file():
        raise WorktreeValidationError("Managed metadata is missing or is not a regular file.")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise WorktreeValidationError("Unable to read managed metadata.") from exc
    if len(payload) > 64 * 1024:
        raise WorktreeValidationError("Managed metadata exceeds its size limit.")
    try:
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError, WorktreeValidationError) as exc:
        raise WorktreeValidationError("Managed metadata is invalid.") from exc
    if not isinstance(raw, dict):
        raise WorktreeValidationError("Managed metadata must be an object.")
    return raw


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorktreeValidationError(f"Managed metadata field {field} is invalid.")
    return value


def _optional_path(value: Any) -> PurePosixPath | None:
    if value is None:
        return None
    text = _string(value, "git_hooks_path")
    if "\\" in text or text.startswith("/") or ":" in text:
        raise WorktreeValidationError("Managed Hook path is unsafe.")
    parts = text.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise WorktreeValidationError("Managed Hook path is unsafe.")
    return PurePosixPath(*parts)


def _time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(_string(value, "timestamp"))
    except ValueError as exc:
        raise WorktreeValidationError("Managed timestamp is invalid.") from exc
    return parsed


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _record_payload(record: WorktreeRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "management_id": record.management_id,
        "repository_id": record.repository_id,
        "name": record.name,
        "canonical_key": record.canonical_key,
        "root": str(record.root),
        "branch_ref": record.branch_ref,
        "base_oid": record.base_oid,
        "git_hooks_path": str(record.git_hooks_path) if record.git_hooks_path else None,
        "task_id": record.task_id,
        "state": record.state.value,
        "created_at": record.created_at.isoformat(),
        "last_used_at": record.last_used_at.isoformat(),
        "retained_reason": record.retained_reason,
    }


def _marker_payload(marker: WorktreeMarker) -> dict[str, Any]:
    return {
        "schema_version": marker.schema_version,
        "management_id": marker.management_id,
        "repository_id": marker.repository_id,
        "name": marker.name,
        "branch_ref": marker.branch_ref,
        "base_oid": marker.base_oid,
        "git_hooks_path": str(marker.git_hooks_path) if marker.git_hooks_path else None,
        "task_id": marker.task_id,
        "ready": marker.ready,
    }


class WorktreeRecordStore:
    def read_record(self, layout: WorktreeLayout) -> WorktreeRecord:
        raw = _read_json(layout.record_path)
        if set(raw) != _RECORD_FIELDS:
            raise WorktreeValidationError("Worktree record fields do not match the schema.")
        try:
            state = WorktreeState(raw["state"])
        except (TypeError, ValueError) as exc:
            raise WorktreeValidationError("Worktree record state is invalid.") from exc
        return WorktreeRecord(
            raw["schema_version"],
            _string(raw["management_id"], "management_id"),
            _string(raw["repository_id"], "repository_id"),
            _string(raw["name"], "name"),
            _string(raw["canonical_key"], "canonical_key"),
            Path(_string(raw["root"], "root")),
            _string(raw["branch_ref"], "branch_ref"),
            _string(raw["base_oid"], "base_oid"),
            _optional_path(raw["git_hooks_path"]),
            _string(raw["task_id"], "task_id"),
            state,
            _time(raw["created_at"]),
            _time(raw["last_used_at"]),
            raw["retained_reason"] if raw["retained_reason"] is None else _string(raw["retained_reason"], "retained_reason"),
        )

    def read_marker(self, layout: WorktreeLayout) -> WorktreeMarker:
        raw = _read_json(layout.marker_path)
        if set(raw) != _MARKER_FIELDS or not isinstance(raw["ready"], bool):
            raise WorktreeValidationError("Worktree marker fields do not match the schema.")
        return WorktreeMarker(
            raw["schema_version"],
            _string(raw["management_id"], "management_id"),
            _string(raw["repository_id"], "repository_id"),
            _string(raw["name"], "name"),
            _string(raw["branch_ref"], "branch_ref"),
            _string(raw["base_oid"], "base_oid"),
            _optional_path(raw["git_hooks_path"]),
            _string(raw["task_id"], "task_id"),
            raw["ready"],
        )

    def write_record(self, record: WorktreeRecord, layout: WorktreeLayout | None = None) -> None:
        target = layout.record_path if layout is not None else self._record_path_from_root(record)
        _atomic_json(target, _record_payload(record))

    def write_marker(self, layout: WorktreeLayout, marker: WorktreeMarker) -> None:
        _atomic_json(layout.marker_path, _marker_payload(marker))

    def update_record(self, layout: WorktreeLayout, management_id: str, **changes: Any) -> WorktreeRecord:
        current = self.read_record(layout)
        if current.management_id != management_id:
            raise WorktreeValidationError("Worktree ownership changed before update.")
        updated = replace(current, **changes)
        self.write_record(updated, layout)
        return updated

    def validate_filesystem_identity(
        self,
        repository: RepositoryIdentity,
        layout: WorktreeLayout,
        allowed_states: set[WorktreeState] | None = None,
    ) -> WorktreeRecord:
        record = self.read_record(layout)
        marker = self.read_marker(layout)
        expected = (
            record.management_id == marker.management_id
            and record.repository_id == marker.repository_id == repository.repository_id
            and record.name == marker.name == layout.name.value
            and record.canonical_key == layout.name.canonical_key
            and record.root == layout.root
            and record.branch_ref == marker.branch_ref == layout.branch_ref
            and record.base_oid == marker.base_oid
            and record.git_hooks_path == marker.git_hooks_path
            and record.task_id == marker.task_id
            and (allowed_states is None or record.state in allowed_states)
            and marker.ready
        )
        if not expected:
            raise WorktreeValidationError("Worktree metadata identity does not match.")
        gitdir = self._read_gitdir(layout.root / ".git", layout.root)
        administrative_root = (repository.common_dir / "worktrees").resolve(strict=False)
        try:
            gitdir.relative_to(administrative_root)
        except ValueError as exc:
            raise WorktreeValidationError("Worktree Git directory is outside the repository administration area.") from exc
        common_dir = self._read_commondir(gitdir)
        if common_dir != repository.common_dir:
            raise WorktreeValidationError("Worktree points at another repository.")
        backlink = Path(self._read_small_text(gitdir / "gitdir"))
        if not backlink.is_absolute():
            backlink = gitdir / backlink
        if backlink.resolve(strict=False) != (layout.root / ".git").resolve(strict=False):
            raise WorktreeValidationError("Worktree Git metadata points at another working directory.")
        head = self._read_small_text(gitdir / "HEAD")
        if head != f"ref: {layout.branch_ref}":
            raise WorktreeValidationError("Worktree points at an unexpected branch.")
        return record

    def remove_owned_metadata(self, layout: WorktreeLayout, management_id: str) -> None:
        for path in (layout.marker_path, layout.record_path):
            if not path.exists():
                continue
            raw = _read_json(path)
            if raw.get("management_id") != management_id:
                raise WorktreeValidationError("Worktree ownership changed before metadata removal.")
            path.unlink()

    def iter_record_paths(self, control_root: Path, limit: int | None = None) -> Iterable[Path]:
        records = control_root / "records"
        if not records.is_dir() or records.is_symlink():
            return ()
        values: list[Path] = []
        for path in records.rglob("*.json"):
            if path.is_file() and not path.is_symlink():
                values.append(path)
                if limit is not None and len(values) >= limit:
                    break
        return tuple(values)

    @staticmethod
    def _record_path_from_root(record: WorktreeRecord) -> Path:
        raise WorktreeValidationError("A Worktree layout is required when writing a record.")

    @staticmethod
    def _read_small_text(path: Path) -> str:
        if is_link_or_reparse(path) or not path.is_file():
            raise WorktreeValidationError("Git administrative metadata is not a regular file.")
        payload = path.read_bytes()
        if len(payload) > 4096:
            raise WorktreeValidationError("Git administrative metadata is too large.")
        try:
            return payload.decode("utf-8").strip()
        except UnicodeError as exc:
            raise WorktreeValidationError("Git administrative metadata is invalid.") from exc

    @classmethod
    def _read_gitdir(cls, pointer: Path, root: Path) -> Path:
        value = cls._read_small_text(pointer)
        if not value.startswith("gitdir: "):
            raise WorktreeValidationError("Worktree .git pointer is invalid.")
        candidate = Path(value[8:])
        if not candidate.is_absolute():
            candidate = root / candidate
        if is_link_or_reparse(candidate):
            raise WorktreeValidationError("Worktree Git directory must not be a link.")
        candidate = candidate.resolve(strict=False)
        if not candidate.is_dir():
            raise WorktreeValidationError("Worktree Git directory is invalid.")
        return candidate

    @classmethod
    def _read_commondir(cls, gitdir: Path) -> Path:
        value = cls._read_small_text(gitdir / "commondir")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = gitdir / candidate
        if is_link_or_reparse(candidate):
            raise WorktreeValidationError("Git common directory must not be a link.")
        return candidate.resolve(strict=False)
