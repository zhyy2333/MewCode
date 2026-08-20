from __future__ import annotations

import asyncio

import pytest

from mewcode.agent import AgentCapacityClosedError, AgentCapacityError, AgentCapacityPool


def test_try_acquire_is_immediate_and_rejects_duplicate_owner() -> None:
    async def scenario() -> None:
        pool = AgentCapacityPool()
        leases = [
            await pool.try_acquire("member", f"m-{index}")
            for index in range(8)
        ]
        assert all(item is not None for item in leases)
        assert await pool.try_acquire("subagent", "ninth") is None
        with pytest.raises(AgentCapacityError):
            await pool.try_acquire("member", "m-0")
        assert pool.active_count == 8
        for lease in leases:
            assert lease is not None
            await lease.close()

    asyncio.run(scenario())


def test_fifo_release_and_cancelled_waiter_cleanup() -> None:
    async def scenario() -> None:
        pool = AgentCapacityPool(1)
        first = await pool.acquire("member", "first")
        second_task = asyncio.create_task(pool.acquire("member", "second"))
        cancelled_task = asyncio.create_task(pool.acquire("member", "cancelled"))
        fourth_task = asyncio.create_task(pool.acquire("member", "fourth"))
        await asyncio.sleep(0)
        cancelled_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_task
        await first.close()
        second = await second_task
        assert second.owner_id == "second"
        assert not fourth_task.done()
        await second.close()
        fourth = await fourth_task
        assert fourth.owner_id == "fourth"
        await fourth.close()
        await fourth.close()
        assert pool.active_count == 0

    asyncio.run(scenario())


def test_close_wakes_waiters_and_rejects_new_requests() -> None:
    async def scenario() -> None:
        pool = AgentCapacityPool(1)
        lease = await pool.acquire("member", "active")
        waiter = asyncio.create_task(pool.acquire("member", "waiting"))
        await asyncio.sleep(0)
        await pool.close()
        with pytest.raises(AgentCapacityClosedError):
            await waiter
        with pytest.raises(AgentCapacityClosedError):
            await pool.try_acquire("member", "new")
        await lease.close()
        assert pool.active_count == 0

    asyncio.run(scenario())
