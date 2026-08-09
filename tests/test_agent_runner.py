from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from mewcode.agent import (
    AgentProgress,
    AgentRunConfig,
    AgentRunStateError,
    AgentStopped,
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    AgentToolResult,
    AgentRunner,
    StopReason,
    ToolScheduler,
)
from mewcode.providers import (
    ChatMessage,
    ModelResponse,
    ProviderError,
    ProviderEvent,
    ProviderFinished,
    ProviderFinishReason,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)
from mewcode.tools import ToolExecution, ToolRegistry, ToolResult, ToolSafety

from tests.fakes import ControlledTool, ScriptedAsyncProvider, collect_async, tool_call


def _runner(provider, *, max_iterations: int = 20, unknown_limit: int = 3):
    return AgentRunner(
        provider,
        ToolScheduler(),
        AgentRunConfig(max_iterations, unknown_limit),
        id_factory=lambda: "run-1",
    )


def test_completed_without_tools() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("hel"), ProviderTextDelta("lo"), ProviderUsage(TokenUsage(3, 2, 5))]]
    )
    run = _runner(provider).start([], "Hi", ToolRegistry([]))
    events = asyncio.run(collect_async(run.events()))

    assert [event.text for event in events if isinstance(event, AgentTextDelta)] == ["hel", "lo"]
    assert events[-1] == AgentStopped(
        "run-1", 1, StopReason.COMPLETED, "hello", TokenUsage(3, 2, 5), None
    )
    assert run.outcome.completed is True
    assert run.outcome.new_messages[0] == ChatMessage("user", "Hi")
    assert run.outcome.final_text == "hello"
    assert provider.calls[0]["max_output_tokens"] == 4096


def test_output_limit_is_not_completed_or_committed() -> None:
    provider = ScriptedAsyncProvider(
        [[
            ProviderTextDelta("partial"),
            ProviderUsage(TokenUsage(3, 4096, 4099)),
            ProviderFinished(ProviderFinishReason.OUTPUT_LIMIT),
        ]]
    )
    run = _runner(provider).start([], "Hi", ToolRegistry([]))
    events = asyncio.run(collect_async(run.events()))

    assert events[-1].reason is StopReason.OUTPUT_LIMIT
    assert run.outcome.completed is False
    assert run.outcome.new_messages == ()
    assert run.outcome.final_text == "partial"


@pytest.mark.parametrize("text", ["", "  \n\t"])
def test_natural_empty_response_is_not_completed_or_committed(text: str) -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta(text)]])
    run = _runner(provider).start([], "Hi", ToolRegistry([]))
    events = asyncio.run(collect_async(run.events()))

    assert events[-1].reason is StopReason.EMPTY_RESPONSE
    assert run.outcome.completed is False
    assert run.outcome.new_messages == ()


def test_react_loop_uses_complete_prior_results() -> None:
    first = tool_call("call-1", "echo", value="one")
    second = tool_call("call-2", "echo", value="two")
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(first), ProviderUsage(TokenUsage(2, 1, 3))],
            [ProviderToolCall(second), ProviderUsage(TokenUsage(3, 1, 4))],
            [ProviderTextDelta("done"), ProviderUsage(TokenUsage(4, 1, 5))],
        ]
    )
    tool = ControlledTool("echo")
    run = _runner(provider).start([], "work", ToolRegistry([tool]))
    events = asyncio.run(collect_async(run.events()))

    assert tool.calls == ["echo", "echo"]
    assert len(provider.calls) == 3
    assert len(provider.calls[1]["messages"]) == 3
    assert len(provider.calls[2]["messages"]) == 5
    assert events[-1].reason is StopReason.COMPLETED
    assert run.outcome.usage == TokenUsage(9, 3, 12)
    assert len([event for event in events if isinstance(event, AgentToolCall)]) == 2
    assert len([event for event in events if isinstance(event, AgentToolResult)]) == 2


def test_multiple_tool_calls_execute_once_and_write_back_as_one_batch() -> None:
    first_call = tool_call("call-1", "first", value="one")
    second_call = tool_call("call-2", "second", value="two")
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(first_call), ProviderToolCall(second_call)],
            [ProviderTextDelta("done")],
        ]
    )
    call_log: list[str] = []
    tools = [ControlledTool("first", calls=call_log), ControlledTool("second", calls=call_log)]
    run = _runner(provider).start([], "work", ToolRegistry(tools))
    events = asyncio.run(collect_async(run.events()))

    assert sorted(call_log) == ["first", "second"]
    assert len(call_log) == 2
    result_message = provider.calls[1]["messages"][-1]
    assert [item["id"] for item in result_message.content] == ["call-1", "call-2"]
    assert len([event for event in events if isinstance(event, AgentToolCall)]) == 2
    assert len([event for event in events if isinstance(event, AgentToolResult)]) == 2
    phases = [event.phase for event in events if isinstance(event, AgentProgress)]
    assert "tool_batch_started" in phases
    assert "tool_batch_completed" in phases
    assert run.outcome.reason is StopReason.COMPLETED


def test_tool_failure_is_paired_and_loop_continues() -> None:
    request = tool_call("call-1", "echo")
    failure = ToolResult(False, "echo", "", "bad arguments")
    provider = ScriptedAsyncProvider(
        [[ProviderToolCall(request)], [ProviderTextDelta("corrected")]]
    )
    tool = ControlledTool("echo", result=failure)
    run = _runner(provider).start([], "work", ToolRegistry([tool]))
    asyncio.run(collect_async(run.events()))

    assert run.outcome.reason is StopReason.COMPLETED
    assert len(run.outcome.new_messages) == 4
    tool_message = provider.calls[1]["messages"][-1]
    assert tool_message.role == "tool"
    assert tool_message.content[0]["error"] == "bad arguments"


def test_iteration_limit_does_not_execute_last_tool_call() -> None:
    scripts = [
        [ProviderToolCall(tool_call(f"call-{index}", "echo"))]
        for index in range(1, 21)
    ]
    provider = ScriptedAsyncProvider(scripts)
    tool = ControlledTool("echo")
    run = _runner(provider).start([], "loop", ToolRegistry([tool]))
    events = asyncio.run(collect_async(run.events()))

    assert len(provider.calls) == 20
    assert len(tool.calls) == 19
    assert events[-1].reason is StopReason.ITERATION_LIMIT
    assert len(run.outcome.new_messages) == 1 + 19 * 2


def test_unknown_tool_limit_recovers_before_limit() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call("1", "missing"))],
            [ProviderToolCall(tool_call("2", "echo"))],
            [ProviderTextDelta("done")],
        ]
    )
    tool = ControlledTool("echo")
    run = _runner(provider).start([], "work", ToolRegistry([tool]))
    asyncio.run(collect_async(run.events()))

    assert run.outcome.reason is StopReason.COMPLETED
    assert tool.calls == ["echo"]


def test_unknown_tool_limit_stops_after_three_unknown_rounds() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderToolCall(tool_call(str(index), "missing"))] for index in range(3)]
    )
    run = _runner(provider).start([], "work", ToolRegistry([]))
    asyncio.run(collect_async(run.events()))

    assert run.outcome.reason is StopReason.UNKNOWN_TOOL_LIMIT
    assert len(provider.calls) == 3
    assert len(run.outcome.new_messages) == 7


def test_stream_error_keeps_prior_iteration_and_partial_text_event() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call("1", "echo"))],
            [ProviderTextDelta("partial"), ProviderError("rate limited secret")],
        ]
    )
    run = _runner(provider).start([], "work", ToolRegistry([ControlledTool("echo")]))
    events = asyncio.run(collect_async(run.events()))

    assert AgentTextDelta("run-1", 2, "partial") in events
    assert run.outcome.reason is StopReason.STREAM_ERROR
    assert run.outcome.error == "rate limited secret"
    assert len(run.outcome.new_messages) == 3
    assert len(provider.calls) == 2


def test_internal_error_stops_without_retry() -> None:
    provider = ScriptedAsyncProvider([RuntimeError("boom")])
    run = _runner(provider).start([], "work", ToolRegistry([]))
    asyncio.run(collect_async(run.events()))

    assert run.outcome.reason is StopReason.ERROR
    assert "boom" in (run.outcome.error or "")
    assert len(provider.calls) == 1


class BlockingProvider(ScriptedAsyncProvider):
    def __init__(self, started: asyncio.Event) -> None:
        super().__init__([])
        self.started = started

    async def stream_reply(
        self,
        messages: list[ChatMessage],
        tools=None,
        *,
        max_output_tokens=4096,
    ) -> AsyncIterator[ProviderEvent]:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "max_output_tokens": max_output_tokens,
            }
        )
        self.started.set()
        await asyncio.Event().wait()
        if False:
            yield ProviderTextDelta("")


def test_cancel_during_provider_stream() -> None:
    async def scenario():
        started = asyncio.Event()
        run = _runner(BlockingProvider(started)).start([], "work", ToolRegistry([]))
        consumer = asyncio.create_task(collect_async(run.events()))
        await started.wait()
        await run.cancel()
        return run, await consumer

    run, events = asyncio.run(scenario())
    assert run.outcome.reason is StopReason.CANCELLED
    assert events[-1].reason is StopReason.CANCELLED
    assert run.outcome.new_messages == ()


def test_cancel_during_tool_batch_pairs_cancelled_result() -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        tool = ControlledTool("echo", started=started, release=release)
        provider = ScriptedAsyncProvider(
            [[ProviderToolCall(tool_call("1", "echo"))]]
        )
        run = _runner(provider).start([], "work", ToolRegistry([tool]))
        consumer = asyncio.create_task(collect_async(run.events()))
        await started.wait()
        await run.cancel()
        return run, tool, await consumer

    run, tool, events = asyncio.run(scenario())
    assert tool.cancelled is True
    assert run.outcome.reason is StopReason.CANCELLED
    assert len(run.outcome.new_messages) == 3
    result_event = next(event for event in events if isinstance(event, AgentToolResult))
    assert result_event.execution.result.metadata["cancelled"] is True


def test_cancel_interrupts_active_side_effect_and_preserves_atomic_history() -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        tool = ControlledTool(
            "write",
            ToolSafety.SIDE_EFFECT,
            started=started,
            release=release,
        )
        provider = ScriptedAsyncProvider(
            [[ProviderToolCall(tool_call("1", "write"))]]
        )
        run = _runner(provider).start([], "work", ToolRegistry([tool]))
        consumer = asyncio.create_task(collect_async(run.events()))
        await started.wait()
        await asyncio.wait_for(run.cancel(), timeout=1)
        return run, tool, await consumer

    run, tool, events = asyncio.run(scenario())
    assert tool.cancelled is True
    assert run.outcome.reason is StopReason.CANCELLED
    assert len(run.outcome.new_messages) == 3
    result_event = next(event for event in events if isinstance(event, AgentToolResult))
    assert result_event.execution.result.metadata["cancelled"] is True


def test_consumer_cancellation_during_side_effect_stops_without_next_iteration() -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        tool = ControlledTool(
            "write",
            ToolSafety.SIDE_EFFECT,
            started=started,
            release=release,
        )
        provider = ScriptedAsyncProvider(
            [[ProviderToolCall(tool_call("1", "write"))]]
        )
        run = _runner(provider).start([], "work", ToolRegistry([tool]))
        consumer = asyncio.create_task(collect_async(run.events()))
        await started.wait()
        consumer.cancel()
        return run, tool, provider, await asyncio.wait_for(consumer, timeout=1)

    run, tool, provider, events = asyncio.run(scenario())
    assert tool.cancelled is True
    assert len(provider.calls) == 1
    assert run.outcome.reason is StopReason.CANCELLED
    assert len(run.outcome.new_messages) == 3
    assert events[-1].reason is StopReason.CANCELLED


def test_consumer_cancellation_during_read_batch_pairs_every_result() -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        first = ControlledTool("first", started=started, release=release)
        second = ControlledTool("second", release=release)
        provider = ScriptedAsyncProvider(
            [[
                ProviderToolCall(tool_call("1", "first")),
                ProviderToolCall(tool_call("2", "second")),
            ]]
        )
        run = _runner(provider).start(
            [], "work", ToolRegistry([first, second])
        )
        consumer = asyncio.create_task(collect_async(run.events()))
        await started.wait()
        consumer.cancel()
        events = await asyncio.wait_for(consumer, timeout=1)
        return run, first, second, provider, events

    run, first, second, provider, events = asyncio.run(scenario())
    assert first.cancelled is True
    assert second.cancelled is True
    assert len(provider.calls) == 1
    assert run.outcome.reason is StopReason.CANCELLED
    assert len(run.outcome.new_messages) == 3
    results = [event for event in events if isinstance(event, AgentToolResult)]
    assert len(results) == 2
    assert all(event.execution.result.metadata["cancelled"] for event in results)


def test_progress_usage_event_order_and_single_stop() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("done"), ProviderUsage(TokenUsage(1, 2, 3))]]
    )
    run = _runner(provider).start([], "work", ToolRegistry([]))
    events = asyncio.run(collect_async(run.events()))

    assert [event.phase for event in events if isinstance(event, AgentProgress)] == [
        "run_started", "iteration_started", "model_completed"
    ]
    assert len([event for event in events if isinstance(event, AgentTokenUsage)]) == 1
    assert len([event for event in events if isinstance(event, AgentStopped)]) == 1
    assert all(event.run_id == "run-1" for event in events)


def test_run_is_single_use_and_outcome_requires_completion() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    run = _runner(provider).start([], "work", ToolRegistry([]))
    with pytest.raises(AgentRunStateError):
        _ = run.outcome
    asyncio.run(collect_async(run.events()))
    asyncio.run(run.cancel())
    asyncio.run(run.cancel())
    assert run.outcome.reason is StopReason.COMPLETED
    with pytest.raises(AgentRunStateError):
        asyncio.run(collect_async(run.events()))
