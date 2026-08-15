from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Iterable

from mewcode.processes import merge_process_environment

from .git import DEFAULT_GIT_TIMEOUT, GitCommandRunner
from .links import DirectoryLinker
from .models import (
    InitializationDiagnostic,
    InitializationResult,
    RepositoryIdentity,
    WorktreeConfig,
    WorktreeInitRule,
    WorktreeLayout,
    WorktreeRuleKind,
    WorktreeValidationError,
)
from .paths import is_link_or_reparse


class WorktreeInitializationError(WorktreeValidationError):
    pass


class InitializationJournal:
    def __init__(self) -> None:
        self._created: list[tuple[Path, str]] = []

    def record_file(self, path: Path) -> None:
        self._created.append((path, "file"))

    def record_directory(self, path: Path) -> None:
        self._created.append((path, "directory"))

    def record_link(self, path: Path) -> None:
        self._created.append((path, "link"))

    def rollback(self) -> None:
        for path, kind in reversed(self._created):
            try:
                if kind == "link" and path.is_symlink():
                    path.unlink()
                elif kind == "file" and path.is_file() and not path.is_symlink():
                    path.unlink()
                elif kind == "directory" and path.is_dir() and not path.is_symlink():
                    path.rmdir()
            except OSError:
                pass


class WorktreeInitializer:
    def __init__(
        self,
        runner: GitCommandRunner | None = None,
        linker: DirectoryLinker | None = None,
    ) -> None:
        self._runner = runner or GitCommandRunner()
        self._linker = linker or DirectoryLinker()

    async def initialize(
        self,
        repository: RepositoryIdentity,
        layout: WorktreeLayout,
        config: WorktreeConfig,
    ) -> InitializationResult:
        journal = InitializationJournal()
        diagnostics: list[InitializationDiagnostic] = []
        hooks_path: PurePosixPath | None = None
        environment = merge_process_environment({}, workspace_root=layout.root)
        try:
            for rule in config.rules:
                try:
                    if rule.kind is WorktreeRuleKind.COPY:
                        await self._copy_rule(repository, layout, config, rule, journal)
                    elif rule.kind is WorktreeRuleKind.LINK:
                        await self._link_rule(repository, layout, rule, journal)
                    else:
                        hooks_path = self._hooks_rule(layout, rule)
                        absolute_hooks = layout.root.joinpath(*hooks_path.parts)
                        environment = merge_process_environment(
                            {},
                            workspace_root=layout.root,
                            git_config=(("core.hooksPath", str(absolute_hooks)),),
                        )
                except (OSError, WorktreeValidationError) as exc:
                    if rule.required:
                        raise WorktreeInitializationError(
                            f"Required {rule.kind.value} rule failed for {rule.path}: {type(exc).__name__}."
                        ) from exc
                    diagnostics.append(
                        InitializationDiagnostic(
                            rule.kind,
                            str(rule.path),
                            f"Optional rule failed: {type(exc).__name__}.",
                        )
                    )
        except BaseException:
            journal.rollback()
            raise
        return InitializationResult(tuple(diagnostics), environment, hooks_path)

    async def _copy_rule(
        self,
        repository: RepositoryIdentity,
        layout: WorktreeLayout,
        config: WorktreeConfig,
        rule: WorktreeInitRule,
        journal: InitializationJournal,
    ) -> None:
        source, target = self._source_target(repository, layout, rule.path)
        if not source.exists() or is_link_or_reparse(source):
            raise WorktreeValidationError("Copy source is missing or is a link.")
        await self._require_ignored_untracked(repository, rule.path)
        if target.exists() or target.is_symlink():
            if source.is_file() and target.is_file() and source.read_bytes() == target.read_bytes():
                return
            raise WorktreeValidationError("Copy target already exists.")
        files = self._enumerate_files(source, config)
        if source.is_file():
            self._ensure_parents(target.parent, layout.root, journal)
            shutil.copyfile(source, target, follow_symlinks=False)
            journal.record_file(target)
            return
        self._ensure_parents(target, layout.root, journal)
        for item in files:
            relative = item.relative_to(source)
            destination = target / relative
            self._ensure_parents(destination.parent, layout.root, journal)
            shutil.copyfile(item, destination, follow_symlinks=False)
            journal.record_file(destination)

    async def _link_rule(
        self,
        repository: RepositoryIdentity,
        layout: WorktreeLayout,
        rule: WorktreeInitRule,
        journal: InitializationJournal,
    ) -> None:
        source, target = self._source_target(repository, layout, rule.path)
        if not source.is_dir() or is_link_or_reparse(source):
            raise WorktreeValidationError("Link source is missing or is not a real directory.")
        await self._require_ignored_untracked(repository, rule.path)
        self._ensure_parents(target.parent, layout.root, journal)
        self._linker.create(source, target)
        journal.record_link(target)

    @staticmethod
    def _hooks_rule(layout: WorktreeLayout, rule: WorktreeInitRule) -> PurePosixPath:
        target = layout.root.joinpath(*rule.path.parts)
        if not target.is_dir() or is_link_or_reparse(target):
            raise WorktreeValidationError("Git Hook path is missing or is not a real directory.")
        if not target.resolve(strict=True).is_relative_to(layout.root.resolve(strict=True)):
            raise WorktreeValidationError("Git Hook path escapes the Worktree.")
        return rule.path

    async def _require_ignored_untracked(self, repository: RepositoryIdentity, path: PurePosixPath) -> None:
        value = path.as_posix()
        tracked = await self._runner.run(
            ("ls-files", "--error-unmatch", "--", value),
            cwd=repository.workspace_root,
            timeout_seconds=DEFAULT_GIT_TIMEOUT,
        )
        if tracked.exit_code == 0:
            raise WorktreeValidationError("Initialization source is tracked by Git.")
        if tracked.exit_code not in {0, 1} or tracked.timed_out or tracked.output_exceeded:
            raise WorktreeValidationError("Unable to verify initialization source tracking.")
        ignored = await self._runner.run(
            ("check-ignore", "-q", "--", value),
            cwd=repository.workspace_root,
            timeout_seconds=DEFAULT_GIT_TIMEOUT,
        )
        if ignored.exit_code != 0 or ignored.timed_out or ignored.output_exceeded:
            raise WorktreeValidationError("Initialization source is not explicitly ignored.")

    @staticmethod
    def _source_target(repository: RepositoryIdentity, layout: WorktreeLayout, path: PurePosixPath) -> tuple[Path, Path]:
        source = repository.workspace_root.joinpath(*path.parts)
        target = layout.root.joinpath(*path.parts)
        source_resolved = source.resolve(strict=False)
        target_parent = target.parent.resolve(strict=False)
        if not source_resolved.is_relative_to(repository.workspace_root) or not target_parent.is_relative_to(layout.root):
            raise WorktreeValidationError("Initialization rule escapes its workspace.")
        current = repository.workspace_root
        for part in path.parts:
            current = current / part
            if is_link_or_reparse(current):
                raise WorktreeValidationError("Initialization source contains a link.")
        return source, target

    @staticmethod
    def _enumerate_files(source: Path, config: WorktreeConfig) -> tuple[Path, ...]:
        if source.is_file():
            size = source.stat().st_size
            if size > config.max_copy_file_bytes:
                raise WorktreeValidationError("Copy source exceeds the per-file limit.")
            return (source,)
        if not source.is_dir():
            raise WorktreeValidationError("Copy source has an unsupported type.")
        files: list[Path] = []
        total = 0
        for root, directories, names in os.walk(source, followlinks=False):
            root_path = Path(root)
            for name in tuple(directories):
                if is_link_or_reparse(root_path / name):
                    raise WorktreeValidationError("Copy source contains a directory link.")
            for name in names:
                item = root_path / name
                if is_link_or_reparse(item) or not item.is_file():
                    raise WorktreeValidationError("Copy source contains an unsupported file.")
                size = item.stat().st_size
                if size > config.max_copy_file_bytes:
                    raise WorktreeValidationError("Copy source exceeds the per-file limit.")
                files.append(item)
                total += size
                if len(files) > config.max_copy_files or total > config.max_copy_total_bytes:
                    raise WorktreeValidationError("Copy source exceeds configured limits.")
        return tuple(files)

    @staticmethod
    def _ensure_parents(path: Path, root: Path, journal: InitializationJournal) -> None:
        if not path.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
            raise WorktreeValidationError("Initialization target escapes the Worktree.")
        missing: list[Path] = []
        current = path
        while current != root and not current.exists():
            if is_link_or_reparse(current):
                raise WorktreeValidationError("Initialization target contains a link.")
            missing.append(current)
            current = current.parent
        if is_link_or_reparse(current):
            raise WorktreeValidationError("Initialization target contains a link.")
        for directory in reversed(missing):
            directory.mkdir()
            journal.record_directory(directory)
