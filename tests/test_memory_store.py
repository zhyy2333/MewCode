from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mewcode.continuity import (
    ContinuityPaths,
    MemoryAction,
    MemoryCategory,
    MemoryConfig,
    MemoryError,
    MemoryIndexEntry,
    MemoryMutation,
    MemoryNote,
    MemoryScope,
    MemoryStore,
    MemoryTurn,
    MemoryUpdatePlan,
)
from mewcode.continuity.memory_store import (
    build_prompt_view,
    decode_note,
    encode_index,
    encode_note,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _paths(tmp_path: Path) -> ContinuityPaths:
    return ContinuityPaths.for_workspace(
        tmp_path / "project", user_root=tmp_path / "user"
    )


def _note(note_id: str = "mem-abcdef", scope=MemoryScope.PROJECT) -> MemoryNote:
    return MemoryNote(
        1,
        note_id,
        scope,
        MemoryCategory.PROJECT_KNOWLEDGE,
        "Python 3.11 | [required]",
        "The project targets Python 3.11.",
        1,
        NOW,
        NOW,
        "20260811-120000-abcd",
    )


def _upsert(scope: MemoryScope, summary: str, body: str = "Useful detail") -> MemoryMutation:
    return MemoryMutation(
        MemoryAction.UPSERT,
        scope,
        category=(
            MemoryCategory.PROJECT_KNOWLEDGE
            if scope is MemoryScope.PROJECT
            else MemoryCategory.USER_PREFERENCE
        ),
        summary=summary,
        body=body,
        priority=1,
    )


def test_note_frontmatter_round_trip_and_strict_fields() -> None:
    note = _note()
    assert decode_note(encode_note(note)) == note
    payload = encode_note(note).replace(b"version: 1", b"version: 2")
    with pytest.raises(MemoryError):
        decode_note(payload)


def test_index_is_sorted_escaped_and_budgeted_at_entry_boundaries() -> None:
    entries = [
        MemoryIndexEntry(
            f"mem-abcde{index}",
            MemoryScope.PROJECT,
            MemoryCategory.REFERENCE,
            f"summary | [{index}]",
            2 if index else 1,
            NOW - timedelta(minutes=index),
            f"notes/mem-abcde{index}.md",
        )
        for index in range(5)
    ]
    payload, kept = encode_index(
        MemoryScope.PROJECT,
        entries,
        MemoryConfig(index_max_lines=8, index_max_bytes=25 * 1024),
    )
    text = payload.decode()
    assert kept[0].note_id == "mem-abcde0"
    assert len(text.splitlines()) <= 8
    assert "\\|" in text and "\\[" in text
    assert text.count("- [") == len(kept)


def test_prompt_view_keeps_project_entries_before_user_entries() -> None:
    project = MemoryIndexEntry(
        "mem-project1", MemoryScope.PROJECT, MemoryCategory.PROJECT_KNOWLEDGE,
        "project rule", 1, NOW, "notes/mem-project1.md"
    )
    user = MemoryIndexEntry(
        "mem-user001", MemoryScope.USER, MemoryCategory.USER_PREFERENCE,
        "user preference", 1, NOW, "notes/mem-user001.md"
    )
    view = build_prompt_view(
        [project], [user], MemoryConfig(index_max_lines=200, index_max_bytes=250)
    )
    assert view.bytes <= 250
    assert view.included_note_ids[0] == "mem-project1"
    assert "instructions take precedence" in view.content


def test_store_applies_both_scopes_and_reloads_indexes(tmp_path: Path) -> None:
    ids = iter(("mem-project1", "mem-user001"))
    store = MemoryStore(_paths(tmp_path), id_factory=lambda: next(ids))
    store.load_indexes()
    plan = MemoryUpdatePlan(
        1,
        (
            _upsert(MemoryScope.PROJECT, "project fact"),
            _upsert(MemoryScope.USER, "prefers concise output"),
        ),
    )
    store.apply(plan, MemoryTurn("session", "request", "answer", NOW))

    assert {entry.note_id for entry in store.catalog()} == {
        "mem-project1", "mem-user001"
    }
    assert store.catalog()[0].scope is MemoryScope.PROJECT
    paths = _paths(tmp_path)
    assert (paths.project_memory_root / "index.md").is_file()
    assert (paths.user_memory_root / "index.md").is_file()
    reloaded = MemoryStore(paths)
    assert set(reloaded.load_indexes().included_note_ids) == {
        "mem-project1", "mem-user001"
    }


def test_invalid_mutation_rejects_entire_plan_without_index_changes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = MemoryStore(paths, id_factory=lambda: "mem-project1")
    store.load_indexes()
    store.apply(
        MemoryUpdatePlan(1, (_upsert(MemoryScope.PROJECT, "safe fact"),)),
        MemoryTurn("session", "request", "answer", NOW),
    )
    before_project = (paths.project_memory_root / "index.md").read_bytes()
    before_user = (paths.user_memory_root / "index.md").read_bytes()
    invalid = MemoryMutation(
        MemoryAction.UPSERT,
        MemoryScope.USER,
        category=MemoryCategory.USER_PREFERENCE,
        summary="Bearer abcdefghijklmnop",
        body="do this",
        priority=1,
    )

    with pytest.raises(MemoryError):
        store.apply(
            MemoryUpdatePlan(1, (_upsert(MemoryScope.PROJECT, "another"), invalid)),
            MemoryTurn("session", "request", "answer", NOW),
        )

    assert (paths.project_memory_root / "index.md").read_bytes() == before_project
    assert (paths.user_memory_root / "index.md").read_bytes() == before_user


def test_update_and_delete_require_matching_existing_scope(tmp_path: Path) -> None:
    store = MemoryStore(_paths(tmp_path), id_factory=lambda: "mem-project1")
    store.load_indexes()
    store.apply(
        MemoryUpdatePlan(1, (_upsert(MemoryScope.PROJECT, "fact"),)),
        MemoryTurn("session", "request", "answer", NOW),
    )
    delete = MemoryMutation(MemoryAction.DELETE, MemoryScope.USER, "mem-project1")
    with pytest.raises(MemoryError):
        store.apply(
            MemoryUpdatePlan(1, (delete,)),
            MemoryTurn("session", "request", "answer", NOW),
        )


def test_cross_scope_transaction_failure_restores_both_old_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mewcode.continuity import memory_store as module

    ids = iter(("mem-project1", "mem-user001", "mem-project2", "mem-user002"))
    paths = _paths(tmp_path)
    store = MemoryStore(paths, id_factory=lambda: next(ids))
    store.load_indexes()
    store.apply(
        MemoryUpdatePlan(
            1,
            (
                _upsert(MemoryScope.PROJECT, "old project"),
                _upsert(MemoryScope.USER, "old user"),
            ),
        ),
        MemoryTurn("session", "request", "answer", NOW),
    )
    old_project = (paths.project_memory_root / "index.md").read_bytes()
    old_user = (paths.user_memory_root / "index.md").read_bytes()
    real_replace = module.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if not failed and Path(target) == paths.project_memory_root / "index.md":
            failed = True
            raise OSError("injected")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_once)
    with pytest.raises(MemoryError):
        store.apply(
            MemoryUpdatePlan(
                1,
                (
                    _upsert(MemoryScope.PROJECT, "new project"),
                    _upsert(MemoryScope.USER, "new user"),
                ),
            ),
            MemoryTurn("session", "request", "answer", NOW),
        )

    assert (paths.project_memory_root / "index.md").read_bytes() == old_project
    assert (paths.user_memory_root / "index.md").read_bytes() == old_user
    assert not store._journal.exists()
