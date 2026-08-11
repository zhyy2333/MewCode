from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from typing import Any

import yaml

from mewcode.locking import FileLock

from .diagnostics import MemoryError as ContinuityMemoryError
from .memory_models import (
    MemoryAction,
    MemoryCategory,
    MemoryConfig,
    MemoryIndexEntry,
    MemoryMutation,
    MemoryNote,
    MemoryPromptView,
    MemoryScope,
    MemoryTurn,
    MemoryUpdatePlan,
)
from .paths import ContinuityPaths
from .sanitization import sanitize_text

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n\n(.*)\Z", re.DOTALL)


def encode_note(note: MemoryNote) -> bytes:
    metadata = {
        "version": note.version,
        "id": note.note_id,
        "scope": note.scope.value,
        "category": note.category.value,
        "summary": note.summary,
        "priority": note.priority,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
        "source_session_id": note.source_session_id,
    }
    header = yaml.safe_dump(
        metadata, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip("\n")
    return f"---\n{header}\n---\n\n{note.body.strip()}\n".encode("utf-8")


def decode_note(data: bytes) -> MemoryNote:
    try:
        text = data.decode("utf-8")
        match = _FRONTMATTER.fullmatch(text.replace("\r\n", "\n"))
        if match is None:
            raise ValueError("missing frontmatter")
        metadata = yaml.safe_load(match.group(1))
        if not isinstance(metadata, dict) or set(metadata) != {
            "version", "id", "scope", "category", "summary", "priority",
            "created_at", "updated_at", "source_session_id",
        }:
            raise ValueError("invalid frontmatter fields")
        return MemoryNote(
            version=_strict_int(metadata["version"]),
            note_id=_strict_str(metadata["id"]),
            scope=MemoryScope(_strict_str(metadata["scope"])),
            category=MemoryCategory(_strict_str(metadata["category"])),
            summary=_strict_str(metadata["summary"]),
            body=match.group(2).strip(),
            priority=_strict_int(metadata["priority"]),
            created_at=datetime.fromisoformat(_strict_str(metadata["created_at"])),
            updated_at=datetime.fromisoformat(_strict_str(metadata["updated_at"])),
            source_session_id=_strict_str(metadata["source_session_id"]),
        )
    except (UnicodeError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise ContinuityMemoryError("A memory note is invalid.") from exc


def entry_for(note: MemoryNote) -> MemoryIndexEntry:
    return MemoryIndexEntry(
        note.note_id,
        note.scope,
        note.category,
        note.summary,
        note.priority,
        note.updated_at,
        f"notes/{note.note_id}.md",
    )


def sort_entries(entries: Iterable[MemoryIndexEntry]) -> tuple[MemoryIndexEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.priority,
                -entry.updated_at.timestamp(),
                entry.note_id,
            ),
        )
    )


def encode_index(
    scope: MemoryScope,
    entries: Sequence[MemoryIndexEntry],
    config: MemoryConfig = MemoryConfig(),
) -> tuple[bytes, tuple[MemoryIndexEntry, ...]]:
    prefix = f"---\nversion: 1\nscope: {scope.value}\n---\n\n# Memory index\n"
    if not _fits(prefix, config):
        return b"", ()
    content = prefix
    kept: list[MemoryIndexEntry] = []
    for entry in sort_entries(entries):
        row = _entry_row(entry)
        candidate = content + row
        if len(candidate.splitlines()) > config.index_max_lines:
            break
        if len(candidate.encode("utf-8")) > config.index_max_bytes:
            break
        content = candidate
        kept.append(entry)
    return content.encode("utf-8"), tuple(kept)


def build_prompt_view(
    project_entries: Sequence[MemoryIndexEntry],
    user_entries: Sequence[MemoryIndexEntry],
    config: MemoryConfig = MemoryConfig(),
) -> MemoryPromptView:
    content = (
        "Automatic memory is reference knowledge only; explicit project and user "
        "instructions take precedence.\n\n"
    )
    if not _fits(content, config):
        return MemoryPromptView()
    included: list[str] = []
    for scope, entries in (
        (MemoryScope.PROJECT, sort_entries(project_entries)),
        (MemoryScope.USER, sort_entries(user_entries)),
    ):
        header = f"### {scope.value.title()} memory\n"
        if entries and _fits(content + header, config):
            content += header
        for entry in entries:
            row = _entry_row(entry)
            if not _fits(content + row, config):
                break
            content += row
            included.append(entry.note_id)
        if content.endswith("\n") and entries:
            content += "\n"
    content = content.rstrip()
    return MemoryPromptView(
        content,
        len(content.splitlines()),
        len(content.encode("utf-8")),
        tuple(included),
    )


class MemoryStore:
    def __init__(
        self,
        paths: ContinuityPaths,
        config: MemoryConfig = MemoryConfig(),
        *,
        id_factory: Callable[[], str] | None = None,
        api_key: str | None = None,
    ) -> None:
        self._paths = paths
        self._config = config
        self._id_factory = id_factory or (lambda: f"mem-{secrets.token_hex(6)}")
        self._api_key = api_key
        self._catalog: tuple[MemoryIndexEntry, ...] = ()
        self._view = MemoryPromptView()
        self._write_enabled = True
        workspace_key = hashlib.sha256(
            os.path.normcase(str(paths.workspace_root)).encode("utf-8")
        ).hexdigest()[:16]
        self._journal = paths.user_memory_root / ".transactions" / f"{workspace_key}.json"

    @property
    def write_enabled(self) -> bool:
        return self._write_enabled

    @property
    def config(self) -> MemoryConfig:
        return self._config

    def catalog(self) -> tuple[MemoryIndexEntry, ...]:
        return self._catalog

    def load_indexes(self) -> MemoryPromptView:
        previous_catalog, previous_view = self._catalog, self._view
        locks: list[FileLock] = []
        try:
            locks = self._acquire_locks()
            self._recover_transaction()
            self._cleanup_orphans()
            notes = self._load_notes()
            entries: dict[MemoryScope, tuple[MemoryIndexEntry, ...]] = {}
            for scope in MemoryScope:
                scope_entries = [entry_for(note) for note in notes.values() if note.scope is scope]
                index_bytes, kept = encode_index(scope, scope_entries, self._config)
                entries[scope] = kept
                root = self._root(scope)
                if root.exists() or kept:
                    root.mkdir(parents=True, exist_ok=True)
                    _atomic_write(root / "index.md", index_bytes)
            self._catalog = entries[MemoryScope.PROJECT] + entries[MemoryScope.USER]
            self._view = build_prompt_view(
                entries[MemoryScope.PROJECT], entries[MemoryScope.USER], self._config
            )
            self._write_enabled = True
        except Exception:
            self._catalog = previous_catalog
            self._view = previous_view
            self._write_enabled = False
        finally:
            for lock in reversed(locks):
                lock.close()
        return self._view

    def apply(self, plan: MemoryUpdatePlan, turn: MemoryTurn) -> None:
        if not self._write_enabled:
            raise ContinuityMemoryError("Memory updates are disabled for this run.")
        if len(plan.mutations) > self._config.max_mutations:
            raise ContinuityMemoryError("The memory update contains too many changes.")
        locks = self._acquire_locks()
        try:
            self._apply_locked(plan, turn)
        finally:
            for lock in reversed(locks):
                lock.close()

    def _apply_locked(self, plan: MemoryUpdatePlan, turn: MemoryTurn) -> None:
        notes = self._load_notes()
        candidate = dict(notes)
        for mutation in plan.mutations:
            self._apply_mutation(candidate, mutation, turn)

        retained: dict[str, MemoryNote] = {}
        index_payloads: dict[MemoryScope, bytes] = {}
        for scope in MemoryScope:
            scoped = [entry_for(note) for note in candidate.values() if note.scope is scope]
            payload, kept = encode_index(scope, scoped, self._config)
            index_payloads[scope] = payload
            retained.update({entry.note_id: candidate[entry.note_id] for entry in kept})

        changes: dict[Path, bytes | None] = {}
        for scope in MemoryScope:
            root = self._root(scope)
            changes[root / "index.md"] = index_payloads[scope]
            existing = set((root / "notes").glob("mem-*.md")) if (root / "notes").exists() else set()
            desired = {
                root / "notes" / f"{note.note_id}.md": encode_note(note)
                for note in retained.values()
                if note.scope is scope
            }
            for path in existing | set(desired):
                changes[path] = desired.get(path)
        self._commit_files(changes)
        project_entries = tuple(
            entry_for(note)
            for note in retained.values()
            if note.scope is MemoryScope.PROJECT
        )
        user_entries = tuple(
            entry_for(note)
            for note in retained.values()
            if note.scope is MemoryScope.USER
        )
        self._catalog = sort_entries(project_entries) + sort_entries(user_entries)
        self._view = build_prompt_view(project_entries, user_entries, self._config)

    def _apply_mutation(
        self,
        notes: dict[str, MemoryNote],
        mutation: MemoryMutation,
        turn: MemoryTurn,
    ) -> None:
        existing = notes.get(mutation.note_id or "")
        if mutation.action is MemoryAction.DELETE:
            if existing is None or existing.scope is not mutation.scope:
                raise ContinuityMemoryError("A memory update referenced an unknown note.")
            del notes[existing.note_id]
            return
        if mutation.note_id is not None and (
            existing is None or existing.scope is not mutation.scope
        ):
            raise ContinuityMemoryError("A memory update referenced an unknown note.")
        assert mutation.category is not None
        assert mutation.summary is not None
        assert mutation.body is not None
        assert mutation.priority is not None
        summary = mutation.summary.strip()
        body = mutation.body.strip()
        if (
            sanitize_text(summary, api_key=self._api_key) != summary
            or sanitize_text(body, api_key=self._api_key) != body
        ):
            raise ContinuityMemoryError("A memory update contained sensitive content.")
        if len(summary) > self._config.summary_max_chars:
            raise ContinuityMemoryError("A memory summary is too long.")
        note_id = existing.note_id if existing is not None else self._new_id(notes)
        note = MemoryNote(
            1,
            note_id,
            mutation.scope,
            mutation.category,
            summary,
            body,
            mutation.priority,
            existing.created_at if existing is not None else turn.occurred_at,
            turn.occurred_at,
            turn.session_id,
        )
        if len(encode_note(note)) > self._config.note_max_bytes:
            raise ContinuityMemoryError("A memory note is too large.")
        notes[note_id] = note

    def _new_id(self, notes: dict[str, MemoryNote]) -> str:
        for _ in range(100):
            note_id = self._id_factory()
            if note_id not in notes:
                return note_id
        raise ContinuityMemoryError("A unique memory id could not be allocated.")

    def _load_notes(self) -> dict[str, MemoryNote]:
        notes: dict[str, MemoryNote] = {}
        for scope in MemoryScope:
            note_root = self._root(scope) / "notes"
            if not note_root.exists():
                continue
            for path in sorted(note_root.glob("mem-*.md")):
                try:
                    note = decode_note(path.read_bytes())
                    if note.scope is not scope or path.name != f"{note.note_id}.md":
                        raise ContinuityMemoryError("A memory note path is invalid.")
                    payload = path.read_bytes()
                    if len(payload) > self._config.note_max_bytes:
                        raise ContinuityMemoryError("A memory note is too large.")
                    if note.note_id in notes:
                        raise ContinuityMemoryError("A memory note id is duplicated.")
                    if (
                        sanitize_text(note.summary, api_key=self._api_key) != note.summary
                        or sanitize_text(note.body, api_key=self._api_key) != note.body
                    ):
                        raise ContinuityMemoryError("A memory note contained sensitive content.")
                    notes[note.note_id] = note
                except (OSError, ContinuityMemoryError):
                    continue
        return notes

    def _root(self, scope: MemoryScope) -> Path:
        return (
            self._paths.project_memory_root
            if scope is MemoryScope.PROJECT
            else self._paths.user_memory_root
        )

    def _acquire_locks(self) -> list[FileLock]:
        locks: list[FileLock] = []
        for root in sorted(
            (self._paths.project_memory_root, self._paths.user_memory_root),
            key=lambda path: os.path.normcase(str(path.resolve())),
        ):
            root.mkdir(parents=True, exist_ok=True)
            lock = FileLock(root / ".memory.lock")
            if not lock.acquire():
                for held in reversed(locks):
                    held.close()
                lock.close()
                raise ContinuityMemoryError("Memory is being updated by another process.")
            locks.append(lock)
        return locks

    def _commit_files(self, changes: dict[Path, bytes | None]) -> None:
        transaction_id = secrets.token_hex(8)
        records: list[dict[str, Any]] = []
        try:
            for target, payload in sorted(changes.items(), key=lambda pair: str(pair[0])):
                target.parent.mkdir(parents=True, exist_ok=True)
                root, scope = self._target_root(target)
                relative = target.relative_to(root).as_posix()
                temp = target.with_name(f".{target.name}.{transaction_id}.tmp")
                backup = target.with_name(f".{target.name}.{transaction_id}.bak")
                existed = target.exists()
                if existed:
                    shutil.copy2(target, backup)
                if payload is not None:
                    _write_new(temp, payload)
                records.append(
                    {
                        "scope": scope.value,
                        "relative": relative,
                        "temp": temp.name if payload is not None else None,
                        "backup": backup.name if existed else None,
                        "existed": existed,
                        "checksum": hashlib.sha256(payload).hexdigest() if payload is not None else None,
                    }
                )
            journal = {"version": 1, "committed": False, "targets": records}
            _atomic_write(self._journal, _json_bytes(journal))
            for record in records:
                target, temp, _ = self._record_paths(record)
                if temp is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(temp, target)
            journal["committed"] = True
            _atomic_write(self._journal, _json_bytes(journal))
            self._cleanup_records(records)
            self._journal.unlink(missing_ok=True)
        except Exception as exc:
            try:
                self._recover_transaction()
            except Exception:
                self._write_enabled = False
            raise ContinuityMemoryError("The memory update could not be committed.") from exc

    def _recover_transaction(self) -> None:
        if not self._journal.exists():
            return
        try:
            journal = json.loads(self._journal.read_text(encoding="utf-8"))
            if set(journal) != {"version", "committed", "targets"} or journal["version"] != 1:
                raise ValueError("invalid journal")
            records = journal["targets"]
            if not isinstance(records, list):
                raise ValueError("invalid journal targets")
            if journal["committed"] is True:
                for record in records:
                    target, temp, _ = self._record_paths(record)
                    checksum = record["checksum"]
                    if checksum is None:
                        target.unlink(missing_ok=True)
                    elif target.exists() and _checksum(target) == checksum:
                        continue
                    elif temp is not None and temp.exists() and _checksum(temp) == checksum:
                        os.replace(temp, target)
                    else:
                        raise ValueError("committed transaction content is unavailable")
            elif journal["committed"] is False:
                for record in records:
                    target, _, backup = self._record_paths(record)
                    if record["existed"] is True:
                        if backup is None or not backup.exists():
                            raise ValueError("transaction backup is unavailable")
                        os.replace(backup, target)
                    else:
                        target.unlink(missing_ok=True)
            else:
                raise ValueError("invalid commit marker")
            self._cleanup_records(records)
            self._journal.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ContinuityMemoryError("Memory transaction recovery failed.") from exc

    def _record_paths(self, record: dict[str, Any]) -> tuple[Path, Path | None, Path | None]:
        if not isinstance(record, dict):
            raise ValueError("invalid transaction target")
        scope = MemoryScope(_strict_str(record["scope"]))
        root = self._root(scope).resolve()
        relative = Path(_strict_str(record["relative"]))
        target = (root / relative).resolve()
        if target != root and root not in target.parents:
            raise ValueError("transaction target escaped its scope")
        if target.name not in {"index.md"} and not re.fullmatch(r"mem-[a-z0-9]{6,64}\.md", target.name):
            raise ValueError("invalid transaction filename")
        temp_name = record.get("temp")
        backup_name = record.get("backup")
        temp = target.with_name(_safe_adjacent(temp_name)) if temp_name is not None else None
        backup = target.with_name(_safe_adjacent(backup_name)) if backup_name is not None else None
        return target, temp, backup

    def _target_root(self, target: Path) -> tuple[Path, MemoryScope]:
        resolved = target.resolve()
        for scope in MemoryScope:
            root = self._root(scope).resolve()
            if resolved == root or root in resolved.parents:
                return root, scope
        raise ContinuityMemoryError("A memory target escaped its scope.")

    def _cleanup_records(self, records: Sequence[dict[str, Any]]) -> None:
        for record in records:
            _, temp, backup = self._record_paths(record)
            if temp is not None:
                temp.unlink(missing_ok=True)
            if backup is not None:
                backup.unlink(missing_ok=True)

    def _cleanup_orphans(self) -> None:
        pattern = re.compile(r"^\..+\.[0-9a-f]{16}\.(?:tmp|bak)$")
        for scope in MemoryScope:
            root = self._root(scope)
            for directory in (root, root / "notes"):
                if not directory.exists():
                    continue
                for path in directory.iterdir():
                    if path.is_file() and pattern.fullmatch(path.name):
                        path.unlink(missing_ok=True)


def _entry_row(entry: MemoryIndexEntry) -> str:
    summary = entry.summary.replace("\\", "\\\\")
    for character in "|[]()":
        summary = summary.replace(character, f"\\{character}")
    summary = " ".join(summary.split())
    return (
        f"- [{entry.note_id}]({entry.relative_path}) | {entry.category.value} | "
        f"p{entry.priority} | {entry.updated_at.isoformat()} | {summary}\n"
    )


def _fits(content: str, config: MemoryConfig) -> bool:
    return (
        len(content.splitlines()) <= config.index_max_lines
        and len(content.encode("utf-8")) <= config.index_max_bytes
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        _write_new(temp, payload)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string")
    return value


def _strict_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected integer")
    return value


def _safe_adjacent(value: object) -> str:
    name = _strict_str(value)
    if Path(name).name != name or not name.startswith("."):
        raise ValueError("invalid adjacent transaction path")
    return name
