from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from mewcode.prompting import PromptPackage
from mewcode.providers import (
    CaptureOnlyRequestBoundary,
    ModelRequest,
    ModelResponse,
    ProviderFinished,
    ProviderFinishReason,
    ProviderTextDelta,
    RequestBoundaryProvider,
    RequestSnapshotSlot,
    TokenUsage,
    bind_request_boundary,
)
from tests.fakes import ScriptedAsyncProvider, collect_async


class RecordingBoundary:
    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.calls: list[ModelRequest] = []

    def prepare(self, request: ModelRequest) -> ModelRequest:
        self.calls.append(request)
        return replace(
            request,
            prompt=PromptPackage(
                request.prompt.stable_system,
                request.prompt.dynamic_system + self.suffix,
            ),
        )


def _request(dynamic: str = "dynamic") -> ModelRequest:
    return ModelRequest(PromptPackage("stable", dynamic), ())


def test_unbound_provider_passes_the_same_request_object() -> None:
    inner = ScriptedAsyncProvider([[ProviderTextDelta("ok")]])
    provider = RequestBoundaryProvider(inner)
    request = _request()

    events = asyncio.run(collect_async(provider.stream_reply(request)))

    assert events == [
        ProviderTextDelta("ok"),
        ProviderFinished(ProviderFinishReason.NATURAL),
    ]
    assert inner.calls[0] is request


def test_binding_is_nested_and_restored_after_exception() -> None:
    async def scenario() -> tuple[str, str, str]:
        inner = ScriptedAsyncProvider([[], [], []])
        provider = RequestBoundaryProvider(inner)
        outer = RecordingBoundary("-outer")
        nested = RecordingBoundary("-nested")
        with bind_request_boundary(outer):
            await collect_async(provider.stream_reply(_request()))
            with pytest.raises(RuntimeError, match="boom"):
                with bind_request_boundary(nested):
                    await collect_async(provider.stream_reply(_request()))
                    raise RuntimeError("boom")
            await collect_async(provider.stream_reply(_request()))
        return tuple(call.prompt.dynamic_system for call in inner.calls)  # type: ignore[return-value]

    assert asyncio.run(scenario()) == (
        "dynamic-outer",
        "dynamic-nested",
        "dynamic-outer",
    )


def test_contextvar_bindings_are_isolated_between_asyncio_tasks() -> None:
    class Provider:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def stream_reply(self, request):
            await asyncio.sleep(0)
            self.requests.append(request)
            if False:
                yield ProviderTextDelta("")

        def assistant_messages(self, response, group_id=None):
            return []

        def tool_result_messages(self, executions, group_id=None):
            return []

    async def scenario() -> set[str]:
        inner = Provider()
        provider = RequestBoundaryProvider(inner)

        async def invoke(suffix: str) -> None:
            with bind_request_boundary(RecordingBoundary(suffix)):
                await collect_async(provider.stream_reply(_request()))

        await asyncio.gather(invoke("-a"), invoke("-b"))
        return {request.prompt.dynamic_system for request in inner.requests}

    assert asyncio.run(scenario()) == {"dynamic-a", "dynamic-b"}


def test_snapshot_slot_captures_once_without_transforming() -> None:
    slot = RequestSnapshotSlot()
    boundary = CaptureOnlyRequestBoundary(slot)
    request = _request()

    assert boundary.prepare(request) is request
    assert slot.request is request
    with pytest.raises(RuntimeError, match="already been captured"):
        boundary.prepare(request)


def test_message_conversion_is_delegated() -> None:
    inner = ScriptedAsyncProvider([[]])
    provider = RequestBoundaryProvider(inner)
    response = ModelResponse(
        "ok",
        (),
        usage=TokenUsage.zero(),
        finish_reason=ProviderFinishReason.NATURAL,
    )

    assert provider.assistant_messages(response) == inner.assistant_messages(response)
    assert provider.tool_result_messages([], "group") == inner.tool_result_messages(
        [], "group"
    )
