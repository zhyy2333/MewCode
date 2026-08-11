from __future__ import annotations

import asyncio

import pytest

from mewcode.prompting import PromptPackage
from mewcode.providers import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ProviderFinished,
    ProviderFinishReason,
    ProviderTextDelta,
    ProviderUsage,
    TokenUsage,
    UsageLedger,
    UsageTrackingProvider,
)


def request() -> ModelRequest:
    return ModelRequest(PromptPackage("system", ""), (ChatMessage("user", "hi"),))


class FakeProvider:
    def __init__(self, events=(), error: Exception | None = None) -> None:
        self.events = list(events)
        self.error = error
        self.assistant_calls = []
        self.tool_calls = []

    async def stream_reply(self, _request):
        for event in self.events:
            await asyncio.sleep(0)
            yield event
        if self.error is not None:
            raise self.error

    def assistant_messages(self, response, group_id=None):
        self.assistant_calls.append((response, group_id))
        return [ChatMessage("assistant", "delegated")]

    def tool_result_messages(self, executions, group_id=None):
        self.tool_calls.append((tuple(executions), group_id))
        return [ChatMessage("user", "delegated")]


async def collect(source):
    return [event async for event in source]


def test_ledger_accumulates_known_and_unknown_fields() -> None:
    ledger = UsageLedger()
    ledger.record(TokenUsage(3, 2, 5, 1, None, 3))
    ledger.record(TokenUsage(4, 1, 5, 2, 1, 4))
    snapshot = ledger.snapshot()
    assert snapshot.usage == TokenUsage(7, 3, 10, 3, None, 7)
    assert snapshot.request_count == 2
    assert snapshot.unreported_request_count == 0

    ledger.record(None)
    snapshot = ledger.snapshot()
    assert snapshot.usage == TokenUsage()
    assert snapshot.request_count == 3
    assert snapshot.unreported_request_count == 1


def test_success_forwards_events_and_records_last_usage_once() -> None:
    usage = TokenUsage(2, 1, 3)
    events = [
        ProviderTextDelta("ok"),
        ProviderUsage(TokenUsage(1, 1, 2)),
        ProviderUsage(usage),
        ProviderFinished(ProviderFinishReason.NATURAL),
    ]
    ledger = UsageLedger()
    provider = UsageTrackingProvider(FakeProvider(events), ledger)
    assert asyncio.run(collect(provider.stream_reply(request()))) == events
    assert ledger.snapshot().usage == usage
    assert ledger.snapshot().request_count == 1


def test_message_conversion_is_delegated() -> None:
    fake = FakeProvider()
    provider = UsageTrackingProvider(fake, UsageLedger())
    response = ModelResponse("", (), TokenUsage.zero(), ProviderFinishReason.NATURAL)
    assert provider.assistant_messages(response, "g")[0].content == "delegated"
    assert provider.tool_result_messages((), "g")[0].content == "delegated"
    assert fake.assistant_calls == [(response, "g")]
    assert fake.tool_calls == [((), "g")]


def test_no_usage_and_exception_are_recorded_as_unreported() -> None:
    for fake in (
        FakeProvider([ProviderFinished(ProviderFinishReason.NATURAL)]),
        FakeProvider(error=RuntimeError("secret failure")),
    ):
        ledger = UsageLedger()
        provider = UsageTrackingProvider(fake, ledger)
        try:
            asyncio.run(collect(provider.stream_reply(request())))
        except RuntimeError:
            pass
        snapshot = ledger.snapshot()
        assert snapshot.request_count == 1
        assert snapshot.unreported_request_count == 1


def test_close_after_usage_records_reported_call_once() -> None:
    async def scenario() -> object:
        usage = TokenUsage(1, 2, 3)
        ledger = UsageLedger()
        provider = UsageTrackingProvider(
            FakeProvider([ProviderUsage(usage), ProviderTextDelta("later")]), ledger
        )
        stream = provider.stream_reply(request())
        assert await anext(stream) == ProviderUsage(usage)
        await stream.aclose()
        return ledger.snapshot()

    snapshot = asyncio.run(scenario())
    assert snapshot.request_count == 1
    assert snapshot.unreported_request_count == 0
    assert snapshot.usage == TokenUsage(1, 2, 3)
