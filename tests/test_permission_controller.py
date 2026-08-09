from __future__ import annotations

import asyncio

import pytest

from mewcode.permissions import PermissionChallenge, PermissionChoice


def test_challenge_resolve_before_and_after_wait() -> None:
    async def scenario() -> None:
        first = PermissionChallenge("p1", "c1", "tool", "target")
        first.resolve(PermissionChoice.ONCE)
        assert await first.wait() == PermissionChoice.ONCE

        second = PermissionChallenge("p2", "c2", "tool", "target")
        waiting = asyncio.create_task(second.wait())
        await asyncio.sleep(0)
        second.resolve(PermissionChoice.SESSION)
        assert await waiting == PermissionChoice.SESSION

    asyncio.run(scenario())


def test_challenge_rejects_duplicate_response_and_cancel_wakes_waiter() -> None:
    async def scenario() -> None:
        challenge = PermissionChallenge("p", "c", "tool", "target")
        challenge.resolve(PermissionChoice.DENY)
        with pytest.raises(RuntimeError):
            challenge.resolve(PermissionChoice.ONCE)

        cancelled = PermissionChallenge("p2", "c2", "tool", "target")
        waiting = asyncio.create_task(cancelled.wait())
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

    asyncio.run(scenario())
