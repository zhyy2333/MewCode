from __future__ import annotations

import asyncio
from typing import Any

from mewcode.agent import AgentProgress, AgentToolResult, ToolScheduler
from mewcode.tools import ToolRegistry, ToolResult, ToolSafety

from tests.fakes import ControlledTool, collect_async, tool_call


class Activity:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.log: list[str] = []


class ActivityTool(ControlledTool):
    def __init__(
        self,
        name: str,
        activity: Activity,
        safety: ToolSafety,
        delay: float,
    ) -> None:
        super().__init__(name, safety)
        self._activity = activity
        self._delay = delay

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self._activity.log.append(f"start:{self.name}")
        self._activity.active += 1
        self._activity.maximum = max(self._activity.maximum, self._activity.active)
        try:
            await asyncio.sleep(self._delay)
        finally:
            self._activity.active -= 1
            self._activity.log.append(f"end:{self.name}")
        return ToolResult(True, self.name, self.name)


def test_partition_mixed_batches_via_progress() -> None:
    registry = ToolRegistry(
        [
            ControlledTool("read-a"),
            ControlledTool("read-b"),
            ControlledTool("write", ToolSafety.SIDE_EFFECT),
            ControlledTool("read-c"),
        ]
    )
    schedule = ToolScheduler().schedule(
        "run", 1,
        [
            tool_call("1", "read-a"),
            tool_call("2", "read-b"),
            tool_call("3", "write"),
            tool_call("4", "read-c"),
        ],
        registry,
    )
    events = asyncio.run(collect_async(schedule.events()))

    starts = [event for event in events if isinstance(event, AgentProgress) and event.phase == "tool_batch_started"]
    assert [event.message for event in starts] == [
        "running 2 tool call(s)",
        "running 1 tool call(s)",
        "running 1 tool call(s)",
    ]


def test_read_concurrency_is_bounded_and_results_stream_by_completion() -> None:
    activity = Activity()
    tools = [
        ActivityTool(f"read-{index}", activity, ToolSafety.READ_ONLY, 0.01 * (6 - index))
        for index in range(6)
    ]
    schedule = ToolScheduler(max_read_concurrency=4).schedule(
        "run", 1,
        [tool_call(str(index), tool.name) for index, tool in enumerate(tools)],
        ToolRegistry(tools),
    )
    events = asyncio.run(collect_async(schedule.events()))

    result_names = [
        event.execution.request.name
        for event in events
        if isinstance(event, AgentToolResult)
    ]
    assert activity.maximum == 4
    assert result_names != [tool.name for tool in tools]
    assert [execution.request.name for execution in schedule.executions] == [
        tool.name for tool in tools
    ]


def test_side_effect_is_an_exclusive_barrier_and_unknown_is_structured() -> None:
    activity = Activity()
    tools = [
        ActivityTool("read-a", activity, ToolSafety.READ_ONLY, 0.01),
        ActivityTool("write", activity, ToolSafety.SIDE_EFFECT, 0.01),
        ActivityTool("read-b", activity, ToolSafety.READ_ONLY, 0.01),
    ]
    schedule = ToolScheduler().schedule(
        "run", 1,
        [
            tool_call("1", "read-a"),
            tool_call("2", "write"),
            tool_call("3", "missing"),
            tool_call("4", "read-b"),
        ],
        ToolRegistry(tools),
    )
    asyncio.run(collect_async(schedule.events()))

    assert activity.maximum == 1
    assert activity.log == [
        "start:read-a", "end:read-a",
        "start:write", "end:write",
        "start:read-b", "end:read-b",
    ]
    missing = schedule.executions[2]
    assert missing.result.ok is False
    assert missing.result.error == "Unknown tool: missing"


def test_cancel_marks_active_and_unstarted_calls() -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        first = ControlledTool("first", started=started, release=release)
        second = ControlledTool("second", ToolSafety.SIDE_EFFECT)
        schedule = ToolScheduler(max_read_concurrency=1).schedule(
            "run", 1,
            [tool_call("1", "first"), tool_call("2", "second")],
            ToolRegistry([first, second]),
        )
        consumer = asyncio.create_task(collect_async(schedule.events()))
        await started.wait()
        await schedule.cancel()
        events = await consumer
        return schedule, first, second, events

    schedule, first, second, events = asyncio.run(scenario())
    assert first.cancelled is True
    assert second.calls == []
    assert len([event for event in events if isinstance(event, AgentToolResult)]) == 2
    assert all(execution.result.metadata.get("cancelled") for execution in schedule.executions)


def test_cancel_interrupts_active_side_effect_and_skips_following_call() -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        side_effect = ControlledTool(
            "write",
            ToolSafety.SIDE_EFFECT,
            started=started,
            release=release,
        )
        following = ControlledTool("read")
        schedule = ToolScheduler().schedule(
            "run",
            1,
            [tool_call("1", "write"), tool_call("2", "read")],
            ToolRegistry([side_effect, following]),
        )
        consumer = asyncio.create_task(collect_async(schedule.events()))
        await started.wait()
        await asyncio.wait_for(schedule.cancel(), timeout=1)
        events = await consumer
        return schedule, side_effect, following, events

    schedule, side_effect, following, events = asyncio.run(scenario())
    assert side_effect.cancelled is True
    assert following.calls == []
    assert len([event for event in events if isinstance(event, AgentToolResult)]) == 2
    assert all(
        execution.result.metadata.get("cancelled")
        for execution in schedule.executions
    )
