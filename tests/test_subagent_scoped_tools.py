from __future__ import annotations

import asyncio

from mewcode.subagents import (
    FileReadObservationCache,
    TaskScopedTool,
    build_task_scoped_registry,
)
from mewcode.tools import ToolRegistry, ToolResult, ToolSafety
from tests.fakes import ControlledTool


def test_proxy_reuses_schema_metadata_and_registry_order() -> None:
    first = ControlledTool("first")
    second = ControlledTool("second", ToolSafety.SIDE_EFFECT)
    cache = FileReadObservationCache()
    registry = build_task_scoped_registry(ToolRegistry([first, second]), cache)
    proxies = registry.list()

    assert registry.names == ("first", "second")
    for proxy, original in zip(proxies, (first, second), strict=True):
        assert proxy.name == original.name
        assert proxy.description == original.description
        assert proxy.parameters_schema is original.parameters_schema
        assert proxy.safety is original.safety
        assert proxy.permission_spec is original.permission_spec


def test_proxy_returns_exact_success_and_failure_results() -> None:
    async def scenario():
        success_result = ToolResult(True, "ok", "content", metadata={"x": 1})
        failure_result = ToolResult(False, "bad", "", "failed")
        success = TaskScopedTool(
            ControlledTool("ok", result=success_result), FileReadObservationCache()
        )
        failure = TaskScopedTool(
            ControlledTool("bad", result=failure_result), FileReadObservationCache()
        )
        return (
            await success.execute({"value": "unchanged"}),
            await failure.execute({"value": "unchanged"}),
        )

    success, failure = asyncio.run(scenario())
    assert success == ToolResult(True, "ok", "content", metadata={"x": 1})
    assert failure == ToolResult(False, "bad", "", "failed")


def test_proxy_propagates_cancellation_to_underlying_coroutine() -> None:
    async def scenario() -> bool:
        started = asyncio.Event()
        release = asyncio.Event()
        underlying = ControlledTool("read", started=started, release=release)
        proxy = TaskScopedTool(underlying, FileReadObservationCache())
        task = asyncio.create_task(proxy.execute({}))
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return underlying.cancelled

    assert asyncio.run(scenario()) is True


def test_file_observations_are_per_task_and_writes_invalidate_only_local_cache() -> None:
    first_cache = FileReadObservationCache()
    second_cache = FileReadObservationCache()
    first_read = TaskScopedTool(
        ControlledTool(
            "read_file",
            result=ToolResult(True, "read_file", "hello", metadata={"path": "src\\a.py"}),
        ),
        first_cache,
    )
    second_read = TaskScopedTool(
        ControlledTool(
            "read_file",
            result=ToolResult(True, "read_file", "hello", metadata={"path": "src/a.py"}),
        ),
        second_cache,
    )
    writer = TaskScopedTool(
        ControlledTool(
            "write_file",
            ToolSafety.SIDE_EFFECT,
            result=ToolResult(True, "write_file", "wrote", metadata={"path": "src/a.py"}),
        ),
        first_cache,
    )

    async def scenario() -> None:
        await first_read.execute({"path": "src/a.py"})
        await second_read.execute({"path": "src/a.py"})
        await writer.execute({"path": "src/a.py", "content": "new"})

    asyncio.run(scenario())
    assert first_cache.observations == {}
    assert second_cache.observations["src/a.py"].bytes_read == 5
    assert len(second_cache.observations["src/a.py"].content_digest) == 64


def test_failed_read_or_write_does_not_modify_observation_cache() -> None:
    cache = FileReadObservationCache()
    cache.observe("a.py", "old")
    read = TaskScopedTool(
        ControlledTool("read_file", result=ToolResult(False, "read_file", "", "bad")),
        cache,
    )
    write = TaskScopedTool(
        ControlledTool("write_file", result=ToolResult(False, "write_file", "", "bad")),
        cache,
    )

    asyncio.run(read.execute({"path": "a.py"}))
    asyncio.run(write.execute({"path": "a.py"}))
    assert cache.observations["a.py"].bytes_read == 3
