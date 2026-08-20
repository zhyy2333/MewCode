from __future__ import annotations

import asyncio
import subprocess
import sys

from mewcode.agent import AgentCapacityPool
from mewcode.subagents import SubagentTaskManager
from mewcode.teams import TeamCoordinator, TeamMemberScheduler


def test_wiring_public_types_import_and_share_capacity_contract() -> None:
    async def scenario() -> None:
        pool = AgentCapacityPool(2)
        manager = SubagentTaskManager(capacity_pool=pool)
        team_slot = await pool.acquire("team_member", "member-1")
        subagent_slot = await pool.try_acquire("subagent", "task-1")
        assert subagent_slot is not None
        assert await pool.try_acquire("team_member", "member-2") is None
        await subagent_slot.close()
        await team_slot.close()
        await manager.close()
        await pool.close()

    asyncio.run(scenario())
    assert TeamCoordinator.__name__ == "TeamCoordinator"
    assert TeamMemberScheduler.__name__ == "TeamMemberScheduler"


def test_installed_module_help_entry_starts() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "mewcode", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert "usage:" in completed.stdout.lower()
