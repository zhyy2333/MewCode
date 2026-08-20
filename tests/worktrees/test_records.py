from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mewcode.worktrees import (
    GitWorktreeBackend,
    SCHEMA_VERSION,
    WorktreeMarker,
    WorktreeOwner,
    WorktreePathPolicy,
    WorktreeRecord,
    WorktreeRecordStore,
    WorktreePurpose,
    WorktreeState,
    WorktreeValidationError,
)

from .helpers import git, repository


def test_record_roundtrip_and_filesystem_identity(tmp_path: Path) -> None:
    root = repository(tmp_path)
    identity = GitWorktreeBackend().discover_repository(root)
    policy = WorktreePathPolicy()
    name = policy.parse_name("task/0123456789abcdef0123456789abcdef")
    layout = policy.layout(identity, name)
    base = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "worktree", "add", "-b", layout.branch_ref.removeprefix("refs/heads/"), str(layout.root), base)
    now = datetime.now(timezone.utc)
    record = WorktreeRecord(SCHEMA_VERSION, "a" * 32, identity.repository_id, name.value, name.canonical_key, layout.root, layout.branch_ref, base, None, "task", WorktreeState.READY, now, now)
    marker = WorktreeMarker(SCHEMA_VERSION, "a" * 32, identity.repository_id, name.value, layout.branch_ref, base, None, "task", True)
    store = WorktreeRecordStore()
    store.write_record(record, layout)
    store.write_marker(layout, marker)
    assert store.validate_filesystem_identity(identity, layout, {WorktreeState.READY}) == record


def test_record_rejects_unknown_duplicate_and_identity_mismatch(tmp_path: Path) -> None:
    root = repository(tmp_path)
    identity = GitWorktreeBackend().discover_repository(root)
    policy = WorktreePathPolicy()
    layout = policy.layout(identity, policy.parse_name("task/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))
    layout.record_path.parent.mkdir(parents=True)
    layout.record_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(WorktreeValidationError):
        WorktreeRecordStore().read_record(layout)


def test_legacy_record_defaults_to_subagent_owner(tmp_path: Path) -> None:
    root = repository(tmp_path)
    identity = GitWorktreeBackend().discover_repository(root)
    policy = WorktreePathPolicy()
    layout = policy.layout(identity, policy.parse_name("task/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
    layout.record_path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "management_id": "b" * 32,
        "repository_id": identity.repository_id,
        "name": layout.name.value,
        "canonical_key": layout.name.canonical_key,
        "root": str(layout.root),
        "branch_ref": layout.branch_ref,
        "base_oid": git(root, "rev-parse", "HEAD").stdout.strip(),
        "git_hooks_path": None,
        "task_id": "legacy-task",
        "state": "ready",
        "created_at": now,
        "last_used_at": now,
        "retained_reason": None,
    }
    layout.record_path.write_text(json.dumps(payload), encoding="utf-8")
    restored = WorktreeRecordStore().read_record(layout)
    assert restored.purpose is WorktreePurpose.SUBAGENT_TASK
    assert restored.owner_id == "legacy-task"
    assert restored.persistent is False
    layout.record_path.write_text(json.dumps({"unknown": True}), encoding="utf-8")
    with pytest.raises(WorktreeValidationError):
        WorktreeRecordStore().read_record(layout)
