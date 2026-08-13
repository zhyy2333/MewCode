from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
import contextvars
from dataclasses import dataclass
from typing import Protocol

from mewcode.tools import ToolExecution

from .base import (
    ChatMessage,
    LLMProvider,
    ModelRequest,
    ModelResponse,
    ProviderEvent,
)


class ProviderRequestBoundary(Protocol):
    def prepare(self, request: ModelRequest) -> ModelRequest: ...


_current_boundary: contextvars.ContextVar[ProviderRequestBoundary | None] = (
    contextvars.ContextVar("mewcode_provider_request_boundary", default=None)
)


@contextmanager
def bind_request_boundary(boundary: ProviderRequestBoundary) -> Iterator[None]:
    token = _current_boundary.set(boundary)
    try:
        yield
    finally:
        _current_boundary.reset(token)


@dataclass
class RequestSnapshotSlot:
    _request: ModelRequest | None = None

    def capture(self, request: ModelRequest) -> None:
        if self._request is not None:
            raise RuntimeError("The request snapshot slot has already been captured.")
        self._request = request

    @property
    def request(self) -> ModelRequest | None:
        return self._request


@dataclass(frozen=True)
class CaptureOnlyRequestBoundary:
    slot: RequestSnapshotSlot

    def prepare(self, request: ModelRequest) -> ModelRequest:
        self.slot.capture(request)
        return request


class RequestBoundaryProvider:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def stream_reply(self, request: ModelRequest) -> AsyncIterator[ProviderEvent]:
        boundary = _current_boundary.get()
        actual_request = boundary.prepare(request) if boundary is not None else request
        async for event in self._provider.stream_reply(actual_request):
            yield event

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
