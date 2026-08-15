from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.worktrees.config import WorktreeConfigLoader
from mewcode.worktrees.lifecycle import WorktreeLifecycleService
from mewcode.worktrees.models import WorktreeDeleteStatus, WorktreeState
from mewcode.worktrees.paths import WorktreePathPolicy

from .helpers import repository


def _service(root: Path) -> WorktreeLifecycleService:
    config = WorktreeConfigLoader().load(root / ".mewcode" / "worktrees.yaml")
    return WorktreeLifecycleService(root, config)


def test_create_recover_enter_exit_and_force_delete(tmp_path: Path) -> None:
    root = repository(tmp_path)
    name = WorktreePathPolicy().parse_name("task/0123456789abcdef0123456789abcdef")

    async def scenario() -> None:
        service = _service(root)
        environment = await service.create_or_recover(name, task_id="one")
        assert environment.record.state is WorktreeState.READY
        assert environment.root.exists()

        recovered = await _service(root).create_or_recover(name, task_id="one")
        assert recovered.record.management_id == environment.record.management_id

        lease = await service.enter(environment, task_id="one")
        (environment.root / "result.txt").write_text("keep", encoding="utf-8")
        exited = await service.exit(lease)
        assert exited.state is WorktreeState.RETAINED
        deleted = await service.delete(name, force=True)
        assert deleted.status is WorktreeDeleteStatus.DELETED
        assert not environment.root.exists()

    asyncio.run(scenario())


def test_clean_exit_deletes_target(tmp_path: Path) -> None:
    root = repository(tmp_path)
    name = WorktreePathPolicy().parse_name("task/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    async def scenario() -> None:
        service = _service(root)
        environment = await service.create_or_recover(name, task_id="clean")
        lease = await service.enter(environment, task_id="clean")
        result = await service.exit(lease)
        assert result.state is WorktreeState.DELETED
        assert not environment.root.exists()

    asyncio.run(scenario())
