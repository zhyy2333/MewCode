from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from mewcode.worktrees.git import GitWorktreeBackend
from mewcode.worktrees.models import SCHEMA_VERSION, WorktreeEnvironment, WorktreeRecord, WorktreeState
from mewcode.worktrees.paths import WorktreePathPolicy

from .helpers import git, repository


def test_discover_resolve_add_protection_and_delete(tmp_path: Path) -> None:
    root = repository(tmp_path)
    backend = GitWorktreeBackend()
    identity = backend.discover_repository(root)
    policy = WorktreePathPolicy()
    name = policy.parse_name("task/0123456789abcdef0123456789abcdef")
    layout = policy.layout(identity, name)

    async def scenario() -> None:
        base = await backend.resolve_head(identity)
        await backend.add(identity, layout, base)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        record = WorktreeRecord(
            SCHEMA_VERSION, "a" * 32, identity.repository_id, name.value,
            name.canonical_key, layout.root, layout.branch_ref, base, None,
            "task", WorktreeState.READY, now, now,
        )
        environment = WorktreeEnvironment(identity, layout, record, {})
        protection = await backend.protection(environment)
        assert protection.safe_to_delete
        (layout.root / "new.txt").write_text("change", encoding="utf-8")
        dirty = await backend.protection(environment)
        assert dirty.untracked_count == 1
        assert not dirty.safe_to_delete
        (layout.root / "new.txt").unlink()
        clean = await backend.protection(environment)
        await backend.remove_worktree(environment, force=False)
        await backend.delete_branch(environment, expected_oid=clean.head_oid or "")

    asyncio.run(scenario())
    assert not layout.root.exists()
    assert git(root, "show-ref", "--verify", layout.branch_ref, check=False).returncode != 0


def test_unpublished_commit_is_protected(tmp_path: Path) -> None:
    root = repository(tmp_path)
    backend = GitWorktreeBackend()
    identity = backend.discover_repository(root)
    policy = WorktreePathPolicy()
    name = policy.parse_name("task/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    layout = policy.layout(identity, name)

    async def scenario() -> None:
        base = await backend.resolve_head(identity)
        await backend.add(identity, layout, base)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        record = WorktreeRecord(SCHEMA_VERSION, "b" * 32, identity.repository_id, name.value, name.canonical_key, layout.root, layout.branch_ref, base, None, "task", WorktreeState.READY, now, now)
        environment = WorktreeEnvironment(identity, layout, record, {})
        (layout.root / "tracked.txt").write_text("committed\n", encoding="utf-8")
        git(layout.root, "add", "tracked.txt")
        git(layout.root, "commit", "-m", "work")
        protected = await backend.protection(environment)
        assert protected.unpublished_commit_count == 1
        assert not protected.safe_to_delete
        await backend.remove_worktree(environment, force=True)
        await backend.delete_branch(environment, expected_oid=protected.head_oid or "")

    asyncio.run(scenario())


def test_conditional_branch_delete_refuses_moved_reference(tmp_path: Path) -> None:
    root = repository(tmp_path)
    backend = GitWorktreeBackend()
    identity = backend.discover_repository(root)
    policy = WorktreePathPolicy()
    name = policy.parse_name("task/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    layout = policy.layout(identity, name)

    async def scenario() -> None:
        base = await backend.resolve_head(identity)
        await backend.add(identity, layout, base)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        record = WorktreeRecord(
            SCHEMA_VERSION, "c" * 32, identity.repository_id, name.value,
            name.canonical_key, layout.root, layout.branch_ref, base, None,
            "task", WorktreeState.READY, now, now,
        )
        environment = WorktreeEnvironment(identity, layout, record, {})
        (layout.root / "tracked.txt").write_text("moved\n", encoding="utf-8")
        git(layout.root, "add", "tracked.txt")
        git(layout.root, "commit", "-m", "move reference")
        moved = git(layout.root, "rev-parse", "HEAD").stdout.strip()
        with __import__("pytest").raises(Exception):
            await backend.delete_branch(environment, expected_oid=base)
        assert await backend.branch_oid(identity, layout.branch_ref) == moved
        await backend.remove_worktree(environment, force=True)
        await backend.delete_branch(environment, expected_oid=moved)

    asyncio.run(scenario())
