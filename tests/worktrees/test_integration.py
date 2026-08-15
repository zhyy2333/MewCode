from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mewcode.worktrees.config import WorktreeConfigLoader
from mewcode.worktrees.git import GitWorktreeBackend
from mewcode.worktrees.lifecycle import WorktreeLifecycleService
from mewcode.worktrees.models import WorktreeDeleteStatus, WorktreeState
from mewcode.worktrees.paths import WorktreePathPolicy
from mewcode.worktrees.records import WorktreeRecordStore

from .helpers import git, repository


def _config(root: Path):
    return WorktreeConfigLoader().load(root / ".mewcode" / "worktrees.yaml")


def test_two_isolated_worktrees_modify_same_relative_path_without_interference(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path)
    (root / "tracked.txt").write_text("main dirty\n", encoding="utf-8")
    policy = WorktreePathPolicy()
    first_name = policy.parse_name("task/11111111111111111111111111111111")
    second_name = policy.parse_name("task/22222222222222222222222222222222")

    async def scenario() -> None:
        service = WorktreeLifecycleService(root, _config(root))
        first, second = await asyncio.gather(
            service.create_or_recover(first_name, task_id="first"),
            service.create_or_recover(second_name, task_id="second"),
        )
        first_lease, second_lease = await asyncio.gather(
            service.enter(first, task_id="first"),
            service.enter(second, task_id="second"),
        )
        assert (first.root / "tracked.txt").read_text(encoding="utf-8") == "base\n"
        assert (second.root / "tracked.txt").read_text(encoding="utf-8") == "base\n"
        assert ".mewcode/worktrees" not in git(root, "status", "--porcelain").stdout

        await asyncio.gather(
            asyncio.to_thread(
                (first.root / "tracked.txt").write_text,
                "first\n",
                encoding="utf-8",
            ),
            asyncio.to_thread(
                (second.root / "tracked.txt").write_text,
                "second\n",
                encoding="utf-8",
            ),
        )
        assert (first.root / "tracked.txt").read_text(encoding="utf-8") == "first\n"
        assert (second.root / "tracked.txt").read_text(encoding="utf-8") == "second\n"
        assert (root / "tracked.txt").read_text(encoding="utf-8") == "main dirty\n"
        assert Path.cwd() != first.root and Path.cwd() != second.root

        first_exit, second_exit = await asyncio.gather(
            service.exit(first_lease),
            service.exit(second_lease),
        )
        assert first_exit.state is WorktreeState.RETAINED
        assert second_exit.state is WorktreeState.RETAINED
        deleted = await asyncio.gather(
            service.delete(first_name, force=True),
            service.delete(second_name, force=True),
        )
        assert all(item.status is WorktreeDeleteStatus.DELETED for item in deleted)

    asyncio.run(scenario())


def test_fast_recovery_uses_no_git_command_and_performs_no_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repository(tmp_path)
    name = WorktreePathPolicy().parse_name("task/33333333333333333333333333333333")

    class ReadOnlyRecords(WorktreeRecordStore):
        def write_record(self, *_args, **_kwargs):
            raise AssertionError("fast recovery attempted to write a record")

        def write_marker(self, *_args, **_kwargs):
            raise AssertionError("fast recovery attempted to write a marker")

        def update_record(self, *_args, **_kwargs):
            raise AssertionError("fast recovery attempted to update a record")

    class DiscoverOnlyGit:
        def __init__(self) -> None:
            self._real = GitWorktreeBackend()

        def discover_repository(self, workspace: Path):
            return self._real.discover_repository(workspace)

        def __getattr__(self, name: str):
            raise AssertionError(f"fast recovery attempted Git operation: {name}")

    async def scenario() -> None:
        owner = WorktreeLifecycleService(root, _config(root))
        created = await owner.create_or_recover(name, task_id="same")
        with monkeypatch.context() as patcher:
            patcher.setattr(
                "mewcode.worktrees.lifecycle.FileLock",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("fast recovery attempted to create or open a lock")
                ),
            )
            recovered = await WorktreeLifecycleService(
                root,
                _config(root),
                records=ReadOnlyRecords(),
                git=DiscoverOnlyGit(),
            ).create_or_recover(name, task_id="same")
        assert recovered.record.management_id == created.record.management_id
        deleted = await owner.delete(name, force=True)
        assert deleted.status is WorktreeDeleteStatus.DELETED

    asyncio.run(scenario())


def test_cross_service_delete_refuses_active_worktree(tmp_path: Path) -> None:
    root = repository(tmp_path)
    name = WorktreePathPolicy().parse_name("task/44444444444444444444444444444444")

    async def scenario() -> None:
        owner = WorktreeLifecycleService(root, _config(root))
        observer = WorktreeLifecycleService(root, _config(root))
        environment = await owner.create_or_recover(name, task_id="active")
        lease = await owner.enter(environment, task_id="active")
        blocked = await observer.delete(name, force=True)
        assert blocked.status is WorktreeDeleteStatus.ACTIVE
        exited = await owner.exit(lease)
        assert exited.state is WorktreeState.DELETED

    asyncio.run(scenario())


def test_expired_crash_stale_active_worktree_is_reclaimed(tmp_path: Path) -> None:
    root = repository(tmp_path)
    name = WorktreePathPolicy().parse_name("task/55555555555555555555555555555555")
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def scenario() -> None:
        owner = WorktreeLifecycleService(root, _config(root), wall_clock=lambda: created_at)
        environment = await owner.create_or_recover(name, task_id="crashed")
        lease = await owner.enter(environment, task_id="crashed")
        # Simulate process death: the OS releases its advisory lock while the
        # durable record remains ACTIVE and no normal exit runs.
        await asyncio.to_thread(lease.lock.close)

        restarted = WorktreeLifecycleService(root, _config(root))
        report = await restarted.cleanup_expired(
            now=created_at + timedelta(hours=25),
            minimum_age=timedelta(hours=24),
            limit=256,
        )
        assert report.deleted == 1
        assert not environment.root.exists()

    asyncio.run(scenario())


def test_retained_commit_can_be_published_then_deleted_without_force(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-u", "origin", "main")
    name = WorktreePathPolicy().parse_name("task/66666666666666666666666666666666")

    async def scenario() -> None:
        service = WorktreeLifecycleService(root, _config(root))
        environment = await service.create_or_recover(name, task_id="publish")
        lease = await service.enter(environment, task_id="publish")
        (environment.root / "tracked.txt").write_text("published\n", encoding="utf-8")
        git(environment.root, "add", "tracked.txt")
        git(environment.root, "commit", "-m", "isolated work")
        retained = await service.exit(lease)
        assert retained.state is WorktreeState.RETAINED
        assert retained.protection is not None
        assert retained.protection.unpublished_commit_count == 1

        git(
            environment.root,
            "push",
            "origin",
            "HEAD:refs/heads/published-worktree",
        )
        deleted = await service.delete(name, force=False)
        assert deleted.status is WorktreeDeleteStatus.DELETED
        assert not environment.root.exists()

    asyncio.run(scenario())


def test_janitor_reports_forged_record_without_following_or_deleting_it(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    identity = GitWorktreeBackend().discover_repository(root)
    forged = identity.common_dir / "mewcode" / "worktrees" / "records" / "forged.json"
    forged.parent.mkdir(parents=True)
    forged.write_text(
        '{"root":"' + str(outside).replace("\\", "\\\\") + '"}',
        encoding="utf-8",
    )

    async def scenario() -> None:
        service = WorktreeLifecycleService(root, _config(root))
        assert await service.list_managed() == ()
        report = await service.cleanup_expired(
            now=datetime.now(timezone.utc) + timedelta(days=2),
            minimum_age=timedelta(hours=24),
            limit=256,
        )
        assert report.deleted == 0
        assert report.diagnostics
        assert sentinel.read_text(encoding="utf-8") == "keep"

    asyncio.run(scenario())
