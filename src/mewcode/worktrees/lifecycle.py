from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import time
from typing import Callable
from uuid import uuid4

from mewcode.locking import FileLock
from mewcode.processes import merge_process_environment

from .git import GitWorktreeBackend
from .initializer import WorktreeInitializer
from .models import (
    CleanupDiagnostic,
    CleanupReport,
    RepositoryIdentity,
    SCHEMA_VERSION,
    WorktreeConfigSnapshot,
    WorktreeDeleteResult,
    WorktreeDeleteStatus,
    WorktreeEnvironment,
    WorktreeError,
    WorktreeExitResult,
    WorktreeLease,
    WorktreeMarker,
    MAX_CLEANUP_CANDIDATES,
    WorktreeName,
    WorktreeProtection,
    WorktreeRecord,
    WorktreeState,
    WorktreeStatus,
    WorktreeValidationError,
)
from .paths import WorktreePathPolicy
from .records import WorktreeRecordStore


CLEANUP_CANDIDATE_TIMEOUT_SECONDS = 10.0


class WorktreeLifecycleService:
    def __init__(
        self,
        workspace: Path,
        config: WorktreeConfigSnapshot,
        *,
        path_policy: WorktreePathPolicy | None = None,
        records: WorktreeRecordStore | None = None,
        git: GitWorktreeBackend | None = None,
        initializer: WorktreeInitializer | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._workspace = workspace.resolve(strict=False)
        self._config = config
        self._paths = path_policy or WorktreePathPolicy()
        self._records = records or WorktreeRecordStore()
        self._git = git or GitWorktreeBackend()
        self._initializer = initializer or WorktreeInitializer()
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._repository: RepositoryIdentity | None = None
        self._repository_error: WorktreeError | None = None
        self._name_locks: dict[str, asyncio.Lock] = {}
        self._repository_lock = asyncio.Lock()
        self._active: dict[str, WorktreeLease] = {}

    def _discover(self) -> RepositoryIdentity:
        if self._repository is not None:
            return self._repository
        if self._repository_error is not None:
            raise self._repository_error
        try:
            self._repository = self._git.discover_repository(self._workspace)
        except WorktreeError as exc:
            self._repository_error = exc
            raise
        return self._repository

    def _lock_for(self, name: WorktreeName) -> asyncio.Lock:
        return self._name_locks.setdefault(name.canonical_key, asyncio.Lock())

    async def create_or_recover(self, name: WorktreeName, *, task_id: str) -> WorktreeEnvironment:
        if not task_id:
            raise WorktreeValidationError("Task ID must not be empty.")
        repository = self._discover()
        layout = self._paths.layout(repository, name)
        async with self._lock_for(name):
            self._paths.validate_ancestors(layout)
            exists = layout.root.exists() or layout.root.is_symlink() or layout.record_path.exists()
            if exists:
                # The common recovery path is intentionally pure filesystem
                # reading: no lock-file creation, Git subprocess, or metadata
                # refresh. enter() obtains occupancy and revalidates afterward.
                return self._recover(repository, layout, task_id)
            operation = FileLock(layout.lock_path)
            if not await asyncio.to_thread(operation.acquire):
                operation.close()
                raise WorktreeValidationError("Worktree is active or being changed in another process.")
            try:
                # A different process may have finished creation between the
                # first existence check and our operation-lock acquisition.
                exists = layout.root.exists() or layout.root.is_symlink() or layout.record_path.exists()
                if exists:
                    return self._recover(repository, layout, task_id)
                if self._config.config is None:
                    raise WorktreeValidationError(self._config.error or "Worktree configuration is invalid.")
                now = self._wall_clock()
                management_id = uuid4().hex
                base_oid = ""
                record: WorktreeRecord | None = None
                environment: WorktreeEnvironment | None = None
                try:
                    async with self._repository_mutation(repository):
                        base_oid = await self._git.resolve_head(repository)
                        record = WorktreeRecord(
                            SCHEMA_VERSION,
                            management_id,
                            repository.repository_id,
                            name.value,
                            name.canonical_key,
                            layout.root,
                            layout.branch_ref,
                            base_oid,
                            None,
                            task_id,
                            WorktreeState.PROVISIONING,
                            now,
                            now,
                        )
                        self._records.write_record(record, layout)
                        await self._git.add(repository, layout, base_oid)
                    initial = await self._initializer.initialize(repository, layout, self._config.config)
                    record = replace(record, git_hooks_path=initial.git_hooks_path)
                    self._records.write_record(record, layout)
                    marker = WorktreeMarker(
                        SCHEMA_VERSION,
                        management_id,
                        repository.repository_id,
                        name.value,
                        layout.branch_ref,
                        base_oid,
                        initial.git_hooks_path,
                        task_id,
                        True,
                    )
                    self._records.write_marker(layout, marker)
                    record = replace(record, state=WorktreeState.READY, last_used_at=self._wall_clock())
                    self._records.write_record(record, layout)
                    environment = WorktreeEnvironment(repository, layout, record, initial.process_environment, initial.diagnostics)
                    return environment
                except BaseException:
                    await self._rollback_new(repository, layout, record, environment, base_oid)
                    raise
            finally:
                await asyncio.to_thread(operation.close)

    def _recover(self, repository: RepositoryIdentity, layout, task_id: str) -> WorktreeEnvironment:
        record = self._records.validate_filesystem_identity(repository, layout, {WorktreeState.READY})
        if record.task_id != task_id:
            raise WorktreeValidationError("Existing Worktree belongs to another task.")
        environment = self._environment_for_record(layout, record)
        return WorktreeEnvironment(repository, layout, record, environment)

    @staticmethod
    def _environment_for_record(layout, record: WorktreeRecord) -> dict[str, str]:
        hooks = ()
        if record.git_hooks_path is not None:
            hooks = (("core.hooksPath", str(layout.root.joinpath(*record.git_hooks_path.parts))),)
        return merge_process_environment({}, workspace_root=layout.root, git_config=hooks)

    async def enter(self, environment: WorktreeEnvironment, *, task_id: str) -> WorktreeLease:
        name = environment.layout.name
        async with self._lock_for(name):
            current = self._records.validate_filesystem_identity(environment.repository, environment.layout, {WorktreeState.READY})
            if current.task_id != task_id:
                raise WorktreeValidationError("Worktree task identity does not match.")
            if name.canonical_key in self._active:
                raise WorktreeValidationError("Worktree is already active.")
            file_lock = FileLock(environment.layout.lock_path)
            if not await asyncio.to_thread(file_lock.acquire):
                file_lock.close()
                raise WorktreeValidationError("Worktree is active in another process.")
            try:
                current = replace(current, state=WorktreeState.ACTIVE, last_used_at=self._wall_clock())
                self._records.write_record(current, environment.layout)
                active_environment = replace(environment, record=current)
                lease = WorktreeLease(active_environment, task_id, file_lock)
                self._active[name.canonical_key] = lease
                return lease
            except BaseException:
                file_lock.close()
                raise

    async def exit(self, lease: WorktreeLease) -> WorktreeExitResult:
        environment = lease.environment
        name = environment.layout.name
        async with self._lock_for(name):
            if lease.released:
                record = self._safe_read(environment)
                state = record.state if record is not None else WorktreeState.DELETED
                return WorktreeExitResult(state, environment.root, environment.branch_ref, None, record.retained_reason if record else None)
            try:
                protection = await self._git.protection(environment)
                if protection.safe_to_delete and protection.head_oid is not None:
                    await self._delete_validated(environment, protection, force=False)
                    result = WorktreeExitResult(WorktreeState.DELETED, environment.root, environment.branch_ref, protection)
                else:
                    reason = protection.reason or "Worktree state is not safe to delete."
                    self._records.update_record(
                        environment.layout,
                        environment.record.management_id,
                        state=WorktreeState.RETAINED,
                        last_used_at=self._wall_clock(),
                        retained_reason=reason,
                    )
                    result = WorktreeExitResult(WorktreeState.RETAINED, environment.root, environment.branch_ref, protection, reason)
                return result
            except BaseException as exc:
                reason = f"Worktree cleanup was interrupted: {type(exc).__name__}."
                try:
                    self._records.update_record(
                        environment.layout,
                        environment.record.management_id,
                        state=WorktreeState.RETAINED,
                        last_used_at=self._wall_clock(),
                        retained_reason=reason,
                    )
                except Exception:
                    pass
                raise
            finally:
                self._active.pop(name.canonical_key, None)
                lease.released = True
                await asyncio.to_thread(lease.lock.close)

    async def delete(self, name: WorktreeName, *, force: bool = False) -> WorktreeDeleteResult:
        repository = self._discover()
        layout = self._paths.layout(repository, name)
        async with self._lock_for(name):
            if name.canonical_key in self._active:
                return WorktreeDeleteResult(WorktreeDeleteStatus.ACTIVE, layout.root, layout.branch_ref, "Worktree is active.")
            if not layout.root.exists() and not layout.record_path.exists():
                return WorktreeDeleteResult(WorktreeDeleteStatus.ALREADY_ABSENT, layout.root, layout.branch_ref)
            occupancy = FileLock(layout.lock_path)
            if not await asyncio.to_thread(occupancy.acquire):
                occupancy.close()
                return WorktreeDeleteResult(
                    WorktreeDeleteStatus.ACTIVE,
                    layout.root,
                    layout.branch_ref,
                    "Worktree is active in another process.",
                )
            try:
                self._paths.validate_delete_target(layout)
                record = self._records.validate_filesystem_identity(repository, layout)
                environment = WorktreeEnvironment(repository, layout, record, self._environment_for_record(layout, record))
                protection = await self._git.protection(environment)
                if protection.check_failed or protection.head_oid is None:
                    return WorktreeDeleteResult(WorktreeDeleteStatus.REJECTED, layout.root, layout.branch_ref, protection.reason)
                if not force and not protection.safe_to_delete:
                    return WorktreeDeleteResult(WorktreeDeleteStatus.RETAINED, layout.root, layout.branch_ref, protection.reason)
                await self._delete_validated(environment, protection, force=force)
                return WorktreeDeleteResult(WorktreeDeleteStatus.DELETED, layout.root, layout.branch_ref)
            except WorktreeError as exc:
                return WorktreeDeleteResult(WorktreeDeleteStatus.REJECTED, layout.root, layout.branch_ref, str(exc))
            finally:
                await asyncio.to_thread(occupancy.close)

    async def list_managed(self) -> tuple[WorktreeStatus, ...]:
        statuses, _diagnostics = self._scan_managed()
        return statuses

    def _scan_managed(
        self,
    ) -> tuple[tuple[WorktreeStatus, ...], tuple[CleanupDiagnostic, ...]]:
        repository = self._discover()
        control_root = repository.common_dir / "mewcode" / "worktrees"
        results: list[WorktreeStatus] = []
        diagnostics: list[CleanupDiagnostic] = []
        for path in self._records.iter_record_paths(
            control_root,
            limit=MAX_CLEANUP_CANDIDATES,
        ):
            candidate_name: str | None = None
            try:
                relative = path.relative_to(control_root / "records").as_posix()
                if not relative.endswith(".json"):
                    continue
                candidate_name = relative[:-5]
                name = self._paths.parse_name(relative[:-5])
                layout = self._paths.layout(repository, name)
                if layout.record_path != path:
                    continue
                record = self._records.validate_filesystem_identity(repository, layout)
                results.append(WorktreeStatus(record.name, record.state, record.root, record.branch_ref, record.last_used_at, record.retained_reason))
            except (OSError, WorktreeError) as exc:
                diagnostics.append(
                    CleanupDiagnostic(
                        candidate_name,
                        f"Managed Worktree candidate was rejected: {type(exc).__name__}.",
                    )
                )
                continue
        return (
            tuple(sorted(results, key=lambda item: item.name)),
            tuple(diagnostics),
        )

    async def cleanup_expired(self, *, now: datetime, minimum_age: timedelta, limit: int) -> CleanupReport:
        if limit < 1:
            return CleanupReport()
        limit = min(limit, MAX_CLEANUP_CANDIDATES)
        statuses, scan_diagnostics = self._scan_managed()
        checked = deleted = retained = 0
        diagnostics: list[CleanupDiagnostic] = list(scan_diagnostics)
        for status in statuses:
            if checked >= limit:
                break
            # ACTIVE is a persisted hint, not proof of a live process. The
            # per-Worktree FileLock below is the authoritative occupancy check,
            # so crash-stale ACTIVE records can eventually be reclaimed.
            if now - status.last_used_at < minimum_age:
                continue
            checked += 1
            try:
                result = await asyncio.wait_for(
                    self.delete(self._paths.parse_name(status.name), force=False),
                    timeout=CLEANUP_CANDIDATE_TIMEOUT_SECONDS,
                )
                if result.status is WorktreeDeleteStatus.DELETED:
                    deleted += 1
                else:
                    retained += 1
                    if result.reason:
                        diagnostics.append(CleanupDiagnostic(status.name, result.reason))
            except TimeoutError:
                retained += 1
                diagnostics.append(
                    CleanupDiagnostic(status.name, "Cleanup candidate timed out.")
                )
            except Exception as exc:
                retained += 1
                diagnostics.append(CleanupDiagnostic(status.name, f"Cleanup failed: {type(exc).__name__}."))
        return CleanupReport(checked, deleted, retained, tuple(diagnostics))

    async def _delete_validated(self, environment: WorktreeEnvironment, protection: WorktreeProtection, *, force: bool) -> None:
        if protection.head_oid is None:
            raise WorktreeValidationError("Current branch identity is unavailable.")
        self._paths.validate_delete_target(environment.layout)
        self._records.validate_filesystem_identity(environment.repository, environment.layout)
        async with self._repository_mutation(environment.repository):
            self._records.update_record(environment.layout, environment.record.management_id, state=WorktreeState.DELETING, last_used_at=self._wall_clock())
            await self._git.remove_worktree(environment, force=force)
            await self._git.delete_branch(environment, expected_oid=protection.head_oid)
        self._records.remove_owned_metadata(environment.layout, environment.record.management_id)
        self._prune_empty_control_parents(environment.layout)

    async def _rollback_new(self, repository, layout, record, environment, base_oid: str) -> None:
        if record is None:
            return
        rollback_env = environment or WorktreeEnvironment(repository, layout, record, {})
        async with self._repository_mutation(repository):
            if layout.root.exists():
                try:
                    await self._git.remove_worktree(rollback_env, force=True)
                except Exception:
                    return
            if base_oid:
                try:
                    await self._git.delete_branch(rollback_env, expected_oid=base_oid)
                except Exception:
                    return
        try:
            self._records.remove_owned_metadata(layout, record.management_id)
        except Exception:
            pass
        self._prune_empty_control_parents(layout)

    @asynccontextmanager
    async def _repository_mutation(self, repository: RepositoryIdentity):
        async with self._repository_lock:
            lock = FileLock(repository.common_dir / "mewcode" / "worktrees" / "locks" / "repository.lock")
            deadline = time.monotonic() + 30.0
            try:
                while not await asyncio.to_thread(lock.acquire):
                    if time.monotonic() >= deadline:
                        raise WorktreeValidationError("Repository Worktree metadata is busy.")
                    await asyncio.sleep(0.05)
                yield
            finally:
                await asyncio.to_thread(lock.close)

    def _safe_read(self, environment: WorktreeEnvironment) -> WorktreeRecord | None:
        try:
            return self._records.read_record(environment.layout)
        except WorktreeError:
            return None

    @staticmethod
    def _prune_empty_control_parents(layout) -> None:
        for path in (layout.record_path.parent, layout.lock_path.parent):
            current = path
            while current != layout.control_root:
                try:
                    current.rmdir()
                except OSError:
                    break
                current = current.parent
