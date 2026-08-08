from __future__ import annotations

import asyncio

import pytest

from mewcode.agent import (
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    StreamCollector,
    StreamStateError,
)
from mewcode.providers import (
    ProviderError,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)

from tests.fakes import collect_async, tool_call


async def _events(*items):
    for item in items:
        await asyncio.sleep(0)
        if isinstance(item, BaseException):
            raise item
        yield item


def test_text_is_streamed_and_collected() -> None:
    collector = StreamCollector("run-1", 1)
    events = asyncio.run(
        collect_async(
            collector.events(
                _events(ProviderTextDelta("hel"), ProviderTextDelta("lo")),
                TokenUsage.zero(),
            )
        )
    )

    assert events == [
        AgentTextDelta("run-1", 1, "hel"),
        AgentTextDelta("run-1", 1, "lo"),
    ]
    assert collector.response.text == "hello"
    assert collector.response.tool_calls == ()
    assert collector.response.usage == TokenUsage()


def test_tool_calls_and_usage_are_collected_once() -> None:
    first = tool_call("call-1", "read_file", path="a.txt")
    second = tool_call("call-2", "find_files", pattern="*.py")
    collector = StreamCollector("run-1", 2)
    events = asyncio.run(
        collect_async(
            collector.events(
                _events(
                    ProviderToolCall(first),
                    ProviderToolCall(second),
                    ProviderUsage(TokenUsage(10, 4, 14)),
                ),
                TokenUsage(20, 5, 25),
            )
        )
    )

    assert [event.request for event in events if isinstance(event, AgentToolCall)] == [
        first,
        second,
    ]
    usage_event = next(event for event in events if isinstance(event, AgentTokenUsage))
    assert usage_event.current == TokenUsage(10, 4, 14)
    assert usage_event.cumulative == TokenUsage(30, 9, 39)
    assert collector.response.tool_calls == (first, second)


def test_unknown_usage_stays_unknown() -> None:
    collector = StreamCollector("run-1", 1)
    events = asyncio.run(
        collect_async(
            collector.events(
                _events(ProviderUsage(TokenUsage(None, 2, None))),
                TokenUsage(10, 3, 13),
            )
        )
    )

    usage_event = next(event for event in events if isinstance(event, AgentTokenUsage))
    assert usage_event.cumulative == TokenUsage(None, 5, None)


def test_error_keeps_emitted_text_but_has_no_response() -> None:
    collector = StreamCollector("run-1", 1)

    async def consume() -> list[object]:
        seen = []
        with pytest.raises(ProviderError):
            async for event in collector.events(
                _events(ProviderTextDelta("partial"), ProviderError("failed")),
                TokenUsage.zero(),
            ):
                seen.append(event)
        return seen

    assert asyncio.run(consume()) == [AgentTextDelta("run-1", 1, "partial")]
    with pytest.raises(StreamStateError):
        _ = collector.response


def test_response_before_completion_and_second_consumption_fail() -> None:
    collector = StreamCollector("run-1", 1)
    with pytest.raises(StreamStateError):
        _ = collector.response

    asyncio.run(collect_async(collector.events(_events(), TokenUsage.zero())))
    with pytest.raises(StreamStateError):
        asyncio.run(collect_async(collector.events(_events(), TokenUsage.zero())))
