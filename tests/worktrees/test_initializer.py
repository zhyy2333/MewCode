from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest

from mewcode.worktrees import (
    GitWorktreeBackend,
    WorktreeConfig,
    WorktreeInitRule,
    WorktreeInitializer,
    WorktreeEnvironment,
    WorktreePathPolicy,
    WorktreeRecord,
    WorktreeRuleKind,
    WorktreeState,
)

from .helpers import git, repository


def test_copy_link_and_hook_initialization(tmp_path: Path) -> None:
    root = repository(tmp_path)
    local = root / "local"
    local.mkdir()
    (local / "settings.txt").write_text("settings", encoding="utf-8")
    dependencies = root / "dependencies"
    dependencies.mkdir()
    (dependencies / "large.bin").write_bytes(b"x" * 1024)
    (root / ".gitignore").write_text((root / ".gitignore").read_text(encoding="utf-8") + "dependencies/\n", encoding="utf-8")
    git(root, "add", ".gitignore")
    git(root, "commit", "-m", "ignore dependencies")
    backend = GitWorktreeBackend()
    identity = backend.discover_repository(root)
    policy = WorktreePathPolicy()
    layout = policy.layout(identity, policy.parse_name("task/0123456789abcdef0123456789abcdef"))

    async def scenario() -> None:
        base = await backend.resolve_head(identity)
        await backend.add(identity, layout, base)
        hooks = layout.root / ".githooks"
        hooks.mkdir()
        config = WorktreeConfig(1, (
            WorktreeInitRule(WorktreeRuleKind.COPY, PurePosixPath("local/settings.txt"), True, "test"),
            WorktreeInitRule(WorktreeRuleKind.LINK, PurePosixPath("dependencies"), True, "test"),
            WorktreeInitRule(WorktreeRuleKind.GIT_HOOKS, PurePosixPath(".githooks"), True, "test"),
        ))
        result = await WorktreeInitializer().initialize(identity, layout, config)
        assert (layout.root / "local" / "settings.txt").read_text(encoding="utf-8") == "settings"
        assert (layout.root / "dependencies").is_symlink()
        assert result.git_hooks_path == PurePosixPath(".githooks")
        assert "core.hooksPath" in result.process_environment.values()
        now = datetime.now(timezone.utc)
        record = WorktreeRecord(
            1, "a" * 32, identity.repository_id, layout.name.value,
            layout.name.canonical_key, layout.root, layout.branch_ref, base,
            None, "task", WorktreeState.READY, now, now,
        )
        await backend.remove_worktree(
            WorktreeEnvironment(identity, layout, record, {}),
            force=True,
        )

    try:
        asyncio.run(scenario())
    except OSError:
        pytest.skip("directory links are unavailable")


def test_required_copy_failure_rolls_back_created_parents(tmp_path: Path) -> None:
    root = repository(tmp_path)
    backend = GitWorktreeBackend()
    identity = backend.discover_repository(root)
    policy = WorktreePathPolicy()
    layout = policy.layout(identity, policy.parse_name("task/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))

    async def scenario() -> None:
        base = await backend.resolve_head(identity)
        await backend.add(identity, layout, base)
        config = WorktreeConfig(1, (WorktreeInitRule(WorktreeRuleKind.COPY, PurePosixPath("missing/file"), True, "test"),))
        with pytest.raises(Exception):
            await WorktreeInitializer().initialize(identity, layout, config)
        assert not (layout.root / "missing").exists()

    asyncio.run(scenario())
