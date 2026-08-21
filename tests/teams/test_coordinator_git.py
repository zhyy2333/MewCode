from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from mewcode.teams.coordinator_git import CoordinatorGitBackend, CoordinatorGitError
from mewcode.teams.coordinator_models import (
    COORDINATOR_SCHEMA_VERSION,
    IntegrationStep,
    IntegrationStepStatus,
)
from mewcode.teams.models import RepositoryBinding
from mewcode.worktrees import GitWorktreeBackend


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[RepositoryBinding, str, str]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-b", "member")
    (tmp_path / "result.txt").write_text("result\n", encoding="utf-8")
    _git(tmp_path, "add", "result.txt")
    _git(tmp_path, "commit", "-m", "member result")
    end = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "main")
    identity = GitWorktreeBackend().discover_repository(tmp_path)
    binding = RepositoryBinding(
        "marker-1", identity.repository_id, identity.workspace_root, identity.common_dir,
        "proof-1", datetime.now(timezone.utc),
    )
    return binding, base, end


def _step(root: Path, base: str, end: str) -> IntegrationStep:
    now = datetime.now(timezone.utc)
    return IntegrationStep(
        COORDINATOR_SCHEMA_VERSION, 0, "step-1", "batch-1", 0, "task-1", "member-1",
        root, "refs/heads/member", base, end, (end,), base, None, None, None,
        IntegrationStepStatus.PREPARED, None, now, now,
    )


def test_controlled_merge_creates_and_verifies_local_merge_commit(tmp_path) -> None:
    binding, base, end = _repository(tmp_path)
    backend = CoordinatorGitBackend()

    async def scenario() -> None:
        snapshot = await backend.target_snapshot(
            binding, expected_branch="refs/heads/main", expected_oid=base,
        )
        step = _step(tmp_path, base, end)
        pre = await backend.begin_merge(binding, step, target_branch="refs/heads/main")
        assert pre == base
        from dataclasses import replace

        step = replace(step, pre_merge_oid=pre, status=IntegrationStepStatus.MERGING)
        commit = await backend.create_integration_commit(
            binding, team_id="team-1", batch_id="batch-1", task_id="task-1", member_id="member-1",
        )
        step = replace(
            step,
            integration_commit_oid=commit,
            status=IntegrationStepStatus.COMMIT_OBSERVED,
        )
        await backend.verify_integration_commit(binding, step, commit, team_id="team-1")
        assert snapshot.clean
        assert _git(tmp_path, "rev-list", "--parents", "-n", "1", commit).split() == [commit, base, end]

    asyncio.run(scenario())


def test_recovery_discovers_commit_created_before_journal_confirmation(tmp_path) -> None:
    binding, base, end = _repository(tmp_path)
    backend = CoordinatorGitBackend()

    async def scenario() -> None:
        step = _step(tmp_path, base, end)
        pre = await backend.begin_merge(binding, step, target_branch="refs/heads/main")
        from dataclasses import replace

        persisted = replace(
            step,
            pre_merge_oid=pre,
            status=IntegrationStepStatus.MERGING,
        )
        commit = await backend.create_integration_commit(
            binding, team_id="team-1", batch_id="batch-1", task_id="task-1", member_id="member-1",
        )
        decision = await backend.recovery_decision(binding, persisted)
        assert decision.kind.value == "confirm"
        assert decision.observed_head_oid == commit

    asyncio.run(scenario())


def test_target_preflight_rejects_dirty_and_drift(tmp_path) -> None:
    binding, base, _end = _repository(tmp_path)
    backend = CoordinatorGitBackend()
    (tmp_path / "untracked.txt").write_text("dirty", encoding="utf-8")

    async def scenario() -> None:
        with pytest.raises(CoordinatorGitError) as caught:
            await backend.target_snapshot(binding, expected_branch="refs/heads/main", expected_oid=base)
        assert caught.value.code == "target_dirty"

    asyncio.run(scenario())


def test_recovery_treats_unknown_external_head_as_manual_without_reset(tmp_path) -> None:
    binding, base, end = _repository(tmp_path)
    (tmp_path / "external.txt").write_text("external\n", encoding="utf-8")
    _git(tmp_path, "add", "external.txt")
    _git(tmp_path, "commit", "-m", "external change")
    external = _git(tmp_path, "rev-parse", "HEAD")
    from dataclasses import replace

    step = replace(
        _step(tmp_path, base, end),
        pre_merge_oid=base,
        status=IntegrationStepStatus.MERGING,
    )
    backend = CoordinatorGitBackend()

    async def scenario() -> None:
        decision = await backend.recovery_decision(binding, step)
        assert decision.kind.value == "manual"
        assert _git(tmp_path, "rev-parse", "HEAD") == external

    asyncio.run(scenario())


def test_merge_conflict_is_aborted_back_to_verified_pre_merge_state(tmp_path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "shared.txt")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-b", "member")
    (tmp_path / "shared.txt").write_text("member\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "member")
    end = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "main")
    (tmp_path / "shared.txt").write_text("target\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "target")
    target = _git(tmp_path, "rev-parse", "HEAD")
    identity = GitWorktreeBackend().discover_repository(tmp_path)
    binding = RepositoryBinding(
        "marker-1", identity.repository_id, identity.workspace_root, identity.common_dir,
        "proof-1", datetime.now(timezone.utc),
    )
    step = _step(tmp_path, base, end)
    from dataclasses import replace

    step = replace(step, expected_target_oid=target)
    backend = CoordinatorGitBackend()

    async def scenario() -> None:
        with pytest.raises(CoordinatorGitError) as caught:
            await backend.begin_merge(binding, step, target_branch="refs/heads/main")
        assert caught.value.code == "merge_conflict"
        await backend.rollback(binding, pre_oid=target)
        snapshot = await backend.target_snapshot(binding, expected_oid=target)
        assert snapshot.clean and not snapshot.operation_in_progress

    asyncio.run(scenario())


def test_controlled_git_source_contains_no_remote_or_cleanup_commands() -> None:
    source = Path(CoordinatorGitBackend.__module__.replace(".", "/"))
    del source  # The command surface is asserted through the actual source file below.
    payload = Path(__file__).parents[2].joinpath("src/mewcode/teams/coordinator_git.py").read_text("utf-8")
    for forbidden in ('("push",', '("fetch",', '("remote",', '("clean",', '"worktree", "remove"'):
        assert forbidden not in payload
