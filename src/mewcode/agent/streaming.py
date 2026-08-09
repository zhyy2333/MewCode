from __future__ import annotations

from collections.abc import AsyncIterator
from enum import Enum, auto

from mewcode.providers import (
    ModelResponse,
    ProviderEvent,
    ProviderFinished,
    ProviderFinishReason,
    ProviderInternalPart,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)

from .events import AgentEvent, AgentTextDelta, AgentTokenUsage, AgentToolCall


class StreamStateError(RuntimeError):
    pass


class _State(Enum):
    NEW = auto()
    CONSUMING = auto()
    COMPLETE = auto()
    FAILED = auto()


class StreamCollector:
    def __init__(self, run_id: str, iteration: int) -> None:
        self._run_id = run_id
        self._iteration = iteration
        self._state = _State.NEW
        self._response: ModelResponse | None = None

    async def events(
        self,
        source: AsyncIterator[ProviderEvent],
        cumulative_usage: TokenUsage,
    ) -> AsyncIterator[AgentEvent]:
        if self._state is not _State.NEW:
            raise StreamStateError("A stream collector can only be consumed once.")
        self._state = _State.CONSUMING
        text_parts: list[str] = []
        tool_calls = []
        internal_parts: list[ProviderInternalPart] = []
        usage = TokenUsage()
        finish_reason: ProviderFinishReason | None = None
        try:
            async for event in source:
                if isinstance(event, ProviderTextDelta):
                    text_parts.append(event.text)
                    yield AgentTextDelta(
                        run_id=self._run_id,
                        iteration=self._iteration,
                        text=event.text,
                    )
                elif isinstance(event, ProviderToolCall):
                    tool_calls.append(event.request)
                    yield AgentToolCall(
                        run_id=self._run_id,
                        iteration=self._iteration,
                        request=event.request,
                    )
                elif isinstance(event, ProviderUsage):
                    usage = event.usage
                    yield AgentTokenUsage(
                        run_id=self._run_id,
                        iteration=self._iteration,
                        current=usage,
                        cumulative=cumulative_usage.add(usage),
                    )
                elif isinstance(event, ProviderInternalPart):
                    internal_parts.append(event)
                elif isinstance(event, ProviderFinished):
                    if finish_reason is not None:
                        raise StreamStateError(
                            "The provider stream emitted more than one finish event."
                        )
                    finish_reason = event.reason
        except BaseException:
            self._state = _State.FAILED
            raise

        if finish_reason is None:
            self._state = _State.FAILED
            raise StreamStateError("The provider stream did not emit a finish event.")
        if finish_reason is ProviderFinishReason.NATURAL and tool_calls:
            self._state = _State.FAILED
            raise StreamStateError(
                "A natural provider finish cannot contain tool calls."
            )
        if finish_reason is ProviderFinishReason.TOOL_CALLS and not tool_calls:
            self._state = _State.FAILED
            raise StreamStateError(
                "A tool-call provider finish must contain at least one tool call."
            )

        self._response = ModelResponse(
            text="".join(text_parts),
            tool_calls=tuple(tool_calls),
            usage=usage,
            finish_reason=finish_reason,
            internal_parts=tuple(internal_parts),
        )
        self._state = _State.COMPLETE

    @property
    def response(self) -> ModelResponse:
        if self._state is not _State.COMPLETE or self._response is None:
            raise StreamStateError("The provider stream did not complete successfully.")
        return self._response
