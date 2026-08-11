from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from mewcode.tools import ToolExecution

from .base import (
    ChatMessage,
    LLMProvider,
    ModelRequest,
    ModelResponse,
    ProviderEvent,
    ProviderUsage,
    TokenUsage,
)


@dataclass(frozen=True)
class UsageSnapshot:
    usage: TokenUsage
    request_count: int
    unreported_request_count: int


class UsageLedger:
    def __init__(self) -> None:
        self._usage = TokenUsage.zero()
        self._request_count = 0
        self._unreported_request_count = 0

    def record(self, usage: TokenUsage | None) -> None:
        self._request_count += 1
        if usage is None:
            self._unreported_request_count += 1
            usage = TokenUsage()
        self._usage = self._usage.add(usage)

    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            self._usage,
            self._request_count,
            self._unreported_request_count,
        )


class UsageTrackingProvider:
    def __init__(self, provider: LLMProvider, ledger: UsageLedger) -> None:
        self._provider = provider
        self._ledger = ledger

    async def stream_reply(self, request: ModelRequest) -> AsyncIterator[ProviderEvent]:
        last_usage: TokenUsage | None = None
        try:
            async for event in self._provider.stream_reply(request):
                if isinstance(event, ProviderUsage):
                    last_usage = event.usage
                yield event
        finally:
            self._ledger.record(last_usage)

    def assistant_messages(
        self, response: ModelResponse, group_id: str | None = None
    ) -> list[ChatMessage]:
        return self._provider.assistant_messages(response, group_id)

    def tool_result_messages(
        self,
        executions: Sequence[ToolExecution],
        group_id: str | None = None,
    ) -> list[ChatMessage]:
        return self._provider.tool_result_messages(executions, group_id)
