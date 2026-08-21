from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from types import MappingProxyType
from typing import Mapping

from mewcode.worktrees import (
    GitCommandResult,
    GitCommandRunner,
    GitWorktreeBackend,
    RepositoryIdentity,
    WorktreeNameFactory,
    WorktreePathPolicy,
    WorktreePurpose,
    WorktreeRecordStore,
    WorktreeState,
)

from .coordinator_models import IntegrationStep, RecoveryDecisionKind, require_branch, require_oid
from .models import RepositoryBinding, TeamMemberRecord, TeamValidationError


MAX_GIT_SUMMARY_CHARS = 512
MAX_INSPECTED_COMMITS = 512
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_EMPTY_ENV: Mapping[str, str] = MappingProxyType({})


class CoordinatorGitError(RuntimeError):
    def __init__(self, code: str, summary: str) -> None:
        if not _SAFE_CODE.fullmatch(code):
            raise ValueError("Coordinator Git error code is invalid.")
        super().__init__(self._bounded(summary))
        self.code = code
        self.summary = self._bounded(summary)

    @staticmethod
    def _bounded(value: str) -> str:
        return " ".join(str(value).splitlines())[:MAX_GIT_SUMMARY_CHARS]


@dataclass(frozen=True)
class GitTargetSnapshot:
    branch_ref: str
    head_oid: str
    clean: bool
    operation_in_progress: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "branch_ref", require_branch(self.branch_ref))
        object.__setattr__(self, "head_oid", require_oid(self.head_oid, "head_oid"))
        if type(self.clean) is not bool or type(self.operation_in_progress) is not bool:
            raise TeamValidationError("Git target snapshot flags must be boolean.")


@dataclass(frozen=True)
class MemberGitSnapshot:
    member_id: str
    worktree_root: Path
    branch_ref: str
    start_oid: str
    end_oid: str
    commit_oids: tuple[str, ...]
    changed_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.member_id:
            raise TeamValidationError("Member Git snapshot identity is missing.")
        root = Path(os.path.abspath(self.worktree_root))
        if not root.is_absolute():
            raise TeamValidationError("Member Worktree root must be absolute.")
        object.__setattr__(self, "worktree_root", root)
        object.__setattr__(self, "branch_ref", require_branch(self.branch_ref))
        object.__setattr__(self, "start_oid", require_oid(self.start_oid, "start_oid"))
        object.__setattr__(self, "end_oid", require_oid(self.end_oid, "end_oid"))
        commits = tuple(require_oid(item, "commit_oid") for item in self.commit_oids)
        if not commits or len(commits) > MAX_INSPECTED_COMMITS or len(set(commits)) != len(commits):
            raise TeamValidationError("Member commit range is invalid.")
        paths = tuple(self.changed_paths)
        if len(paths) > 4096 or any(not item or "\x00" in item or len(item) > 1024 for item in paths):
            raise TeamValidationError("Member changed-path summary is invalid.")
        object.__setattr__(self, "commit_oids", commits)
        object.__setattr__(self, "changed_paths", paths)


@dataclass(frozen=True)
class GitRecoveryDecision:
    kind: RecoveryDecisionKind
    code: str
    observed_head_oid: str

    def __post_init__(self) -> None:
        if not _SAFE_CODE.fullmatch(self.code):
            raise TeamValidationError("Git recovery code is invalid.")
        object.__setattr__(self, "observed_head_oid", require_oid(self.observed_head_oid, "observed_head_oid"))


class CoordinatorGitBackend:
    """A deliberately closed Git command surface for local coordinator integration."""

    def __init__(
        self,
        runner: GitCommandRunner | None = None,
        *,
        worktree_backend: GitWorktreeBackend | None = None,
        path_policy: WorktreePathPolicy | None = None,
        records: WorktreeRecordStore | None = None,
    ) -> None:
        self._runner = runner or GitCommandRunner()
        self._worktree_backend = worktree_backend or GitWorktreeBackend(self._runner)
        self._paths = path_policy or WorktreePathPolicy()
        self._records = records or WorktreeRecordStore()
        self._names = WorktreeNameFactory()

    async def target_snapshot(
        self,
        binding: RepositoryBinding,
        *,
        expected_branch: str | None = None,
        expected_oid: str | None = None,
        require_clean: bool = True,
    ) -> GitTargetSnapshot:
        repository = self._repository(binding)
        branch = self._decode_ascii(
            (await self._run(("symbolic-ref", "-q", "HEAD"), repository.workspace_root, "detached_head")).stdout,
            "branch",
        )
        branch = require_branch(branch)
        head = self._oid(
            (await self._run(("rev-parse", "--verify", "HEAD^{commit}"), repository.workspace_root, "head_unavailable")).stdout
        )
        status = await self._run(
            ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
            repository.workspace_root,
            "status_failed",
        )
        clean = not status.stdout
        in_progress = self._operation_in_progress(repository.common_dir)
        if expected_branch is not None and branch != require_branch(expected_branch):
            raise CoordinatorGitError("target_branch_drift", "The bound target branch changed.")
        if expected_oid is not None and head != require_oid(expected_oid, "expected_oid"):
            raise CoordinatorGitError("target_baseline_drift", "The target branch baseline changed.")
        if require_clean and not clean:
            raise CoordinatorGitError("target_dirty", "The target Worktree is not clean.")
        if in_progress:
            raise CoordinatorGitError("git_operation_in_progress", "Another Git operation is in progress.")
        return GitTargetSnapshot(branch, head, clean, in_progress)

    async def inspect_member(
        self,
        binding: RepositoryBinding,
        team_id: str,
        member: TeamMemberRecord,
        *,
        start_oid: str,
    ) -> MemberGitSnapshot:
        end_oid, branch, root = await self.member_head(binding, team_id, member)
        start = require_oid(start_oid, "start_oid")
        ancestor = await self._runner.run(
            ("merge-base", "--is-ancestor", start, end_oid),
            cwd=root,
            environment=_EMPTY_ENV,
        )
        if ancestor.exit_code != 0 or ancestor.timed_out or ancestor.output_exceeded:
            raise CoordinatorGitError("invalid_commit_range", "The recorded start commit is not an ancestor of the member result.")
        commits_result = await self._run(
            ("rev-list", "--reverse", "--topo-order", f"{start}..{end_oid}"),
            root,
            "commit_range_failed",
        )
        commits = tuple(self._oid(line) for line in commits_result.stdout.splitlines() if line.strip())
        if not commits:
            raise CoordinatorGitError("empty_commit_range", "The member result contains no commits.")
        if len(commits) > MAX_INSPECTED_COMMITS:
            raise CoordinatorGitError("commit_range_too_large", "The member commit range exceeds the safety limit.")
        paths_result = await self._run(
            ("diff", "--name-only", "-z", start, end_oid),
            root,
            "changed_paths_failed",
        )
        changed_paths = tuple(
            value.decode("utf-8", errors="replace")[:1024]
            for value in paths_result.stdout.split(b"\x00")
            if value
        )
        return MemberGitSnapshot(member.member_id, root, branch, start, end_oid, commits, changed_paths)

    async def member_head(
        self,
        binding: RepositoryBinding,
        team_id: str,
        member: TeamMemberRecord,
    ) -> tuple[str, str, Path]:
        repository = self._repository(binding)
        name = self._names.for_team_member(team_id, member.member_id)
        layout = self._paths.layout(repository, name)
        self._paths.validate_ancestors(layout)
        record = self._records.validate_filesystem_identity(
            repository,
            layout,
            {WorktreeState.READY, WorktreeState.ACTIVE, WorktreeState.RETAINED},
        )
        if (
            record.purpose is not WorktreePurpose.TEAM_MEMBER
            or not record.persistent
            or record.owner_id != member.member_id
            or record.root != member.worktree_root
            or record.name != member.worktree_name
            or member.worktree_owner_id != member.member_id
        ):
            raise CoordinatorGitError("worktree_owner_mismatch", "Member Worktree ownership is invalid.")
        status = await self._run(
            ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
            layout.root,
            "member_status_failed",
        )
        if status.stdout:
            raise CoordinatorGitError("member_worktree_dirty", "Member Worktree contains uncommitted changes.")
        branch = self._decode_ascii(
            (await self._run(("symbolic-ref", "-q", "HEAD"), layout.root, "member_detached_head")).stdout,
            "branch",
        )
        if branch != record.branch_ref:
            raise CoordinatorGitError("member_branch_drift", "Member Worktree branch changed.")
        end_oid = self._oid(
            (await self._run(("rev-parse", "--verify", "HEAD^{commit}"), layout.root, "member_head_unavailable")).stdout
        )
        return end_oid, branch, layout.root

    async def begin_merge(
        self,
        binding: RepositoryBinding,
        step: IntegrationStep,
        *,
        target_branch: str,
    ) -> str:
        target = await self.target_snapshot(
            binding,
            expected_branch=target_branch,
            expected_oid=step.expected_target_oid,
        )
        result = await self._runner.run(
            ("merge", "--no-ff", "--no-commit", step.end_oid),
            cwd=binding.workspace_root,
            environment=_EMPTY_ENV,
        )
        if result.timed_out or result.output_exceeded or result.exit_code != 0:
            code = "merge_conflict" if self._operation_in_progress(binding.common_dir) else "merge_failed"
            raise CoordinatorGitError(code, "The controlled local merge did not complete cleanly.")
        return target.head_oid

    async def create_integration_commit(
        self,
        binding: RepositoryBinding,
        *,
        team_id: str,
        batch_id: str,
        task_id: str,
        member_id: str,
    ) -> str:
        message = (
            "MewCode coordinator integration\n\n"
            f"MewCode-Team: {team_id}\n"
            f"MewCode-Batch: {batch_id}\n"
            f"MewCode-Task: {task_id}\n"
            f"MewCode-Member: {member_id}"
        )
        await self._run(
            (
                "-c", "user.name=MewCode Coordinator",
                "-c", "user.email=coordinator@localhost",
                "commit", "--no-gpg-sign", "-m", message,
            ),
            binding.workspace_root,
            "commit_failed",
        )
        return self._oid(
            (await self._run(("rev-parse", "--verify", "HEAD^{commit}"), binding.workspace_root, "head_unavailable")).stdout
        )

    async def verify_integration_commit(
        self,
        binding: RepositoryBinding,
        step: IntegrationStep,
        commit_oid: str,
        *,
        team_id: str | None = None,
    ) -> None:
        oid = require_oid(commit_oid, "commit_oid")
        target = await self.target_snapshot(binding, expected_oid=oid)
        parents = self._decode_ascii(
            (await self._run(("show", "-s", "--format=%P", oid), binding.workspace_root, "verify_parents_failed")).stdout,
            "parents",
        ).split()
        if len(parents) != 2 or parents[0] != step.pre_merge_oid or parents[1] != step.end_oid:
            raise CoordinatorGitError("merge_parent_mismatch", "The integration commit parents are not the expected commits.")
        message = (
            await self._run(("show", "-s", "--format=%B", oid), binding.workspace_root, "verify_trailers_failed")
        ).stdout.decode("utf-8", errors="replace")
        expected_trailers = (
            f"MewCode-Batch: {step.batch_id}",
            f"MewCode-Task: {step.task_id}",
            f"MewCode-Member: {step.member_id}",
        )
        if team_id is not None:
            expected_trailers = (f"MewCode-Team: {team_id}", *expected_trailers)
        if any(message.count(item) != 1 for item in expected_trailers):
            raise CoordinatorGitError("merge_trailer_mismatch", "The integration commit identity trailers are invalid.")
        if not target.clean:
            raise CoordinatorGitError("postcheck_dirty", "The target Worktree is dirty after integration.")

    async def rollback(self, binding: RepositoryBinding, *, pre_oid: str) -> None:
        expected = require_oid(pre_oid, "pre_oid")
        if self._operation_in_progress(binding.common_dir):
            result = await self._runner.run(("merge", "--abort"), cwd=binding.workspace_root, environment=_EMPTY_ENV)
            if result.exit_code != 0 or result.timed_out or result.output_exceeded:
                raise CoordinatorGitError("rollback_failed", "Git could not abort the incomplete merge.")
        current = await self.target_snapshot(binding, require_clean=True)
        if current.head_oid != expected:
            await self._run(("reset", "--hard", expected), binding.workspace_root, "rollback_failed")
            await self.target_snapshot(binding, expected_oid=expected, require_clean=True)

    async def recovery_decision(
        self,
        binding: RepositoryBinding,
        step: IntegrationStep,
    ) -> GitRecoveryDecision:
        repository = self._repository(binding)
        head = self._oid(
            (await self._run(("rev-parse", "--verify", "HEAD^{commit}"), repository.workspace_root, "head_unavailable")).stdout
        )
        if step.integration_commit_oid is not None and head == step.integration_commit_oid:
            return GitRecoveryDecision(RecoveryDecisionKind.CONFIRM, "commit_observed", head)
        if self._operation_in_progress(repository.common_dir):
            return GitRecoveryDecision(RecoveryDecisionKind.ROLLBACK, "merge_in_progress", head)
        if step.pre_merge_oid is not None and head == step.pre_merge_oid:
            return GitRecoveryDecision(RecoveryDecisionKind.RETRY, "pre_merge_restored", head)
        if step.pre_merge_oid is not None and await self._commit_matches_step(
            repository.workspace_root, step, head,
        ):
            return GitRecoveryDecision(RecoveryDecisionKind.CONFIRM, "commit_discovered", head)
        return GitRecoveryDecision(RecoveryDecisionKind.MANUAL, "unrecognized_git_state", head)

    async def _commit_matches_step(self, root: Path, step: IntegrationStep, oid: str) -> bool:
        try:
            parents = self._decode_ascii(
                (await self._run(("show", "-s", "--format=%P", oid), root, "recovery_parents_failed")).stdout,
                "parents",
            ).split()
            if parents != [step.pre_merge_oid, step.end_oid]:
                return False
            message = (
                await self._run(("show", "-s", "--format=%B", oid), root, "recovery_trailers_failed")
            ).stdout.decode("utf-8", errors="replace")
            expected = (
                f"MewCode-Batch: {step.batch_id}",
                f"MewCode-Task: {step.task_id}",
                f"MewCode-Member: {step.member_id}",
            )
            return all(message.count(item) == 1 for item in expected)
        except CoordinatorGitError:
            return False

    def _repository(self, binding: RepositoryBinding) -> RepositoryIdentity:
        discovered = self._worktree_backend.discover_repository(binding.workspace_root)
        expected_root = Path(os.path.abspath(binding.workspace_root))
        expected_common = Path(os.path.abspath(binding.common_dir))
        if (
            discovered.workspace_root != expected_root
            or discovered.common_dir != expected_common
            or discovered.repository_id != binding.repository_id
        ):
            raise CoordinatorGitError("repository_binding_mismatch", "The bound repository identity changed.")
        return discovered

    async def _run(self, args: tuple[str, ...], cwd: Path, code: str) -> GitCommandResult:
        result = await self._runner.run(args, cwd=cwd, environment=_EMPTY_ENV)
        if result.timed_out:
            raise CoordinatorGitError(f"{code}_timeout", "The Git operation timed out.")
        if result.output_exceeded:
            raise CoordinatorGitError(f"{code}_output", "The Git operation exceeded its output limit.")
        if result.exit_code != 0:
            raise CoordinatorGitError(code, "The Git operation failed.")
        return result

    @staticmethod
    def _operation_in_progress(common_dir: Path) -> bool:
        names = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")
        return any((common_dir / name).exists() for name in names)

    @staticmethod
    def _oid(payload: bytes | str) -> str:
        value = payload.decode("ascii", errors="strict").strip() if isinstance(payload, bytes) else payload.strip()
        return require_oid(value, "git_oid")

    @staticmethod
    def _decode_ascii(payload: bytes, field: str) -> str:
        try:
            return payload.decode("ascii", errors="strict").strip()
        except UnicodeError as exc:
            raise CoordinatorGitError("invalid_git_output", f"Git returned an invalid {field} value.") from exc
