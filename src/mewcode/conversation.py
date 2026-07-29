from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from typing import Literal

from .providers import ChatMessage, LLMProvider, ProviderTextDelta, ProviderToolCall
from .tools import ToolRegistry


@dataclass(frozen=True)
class ConversationTextDelta:
    text: str


@dataclass(frozen=True)
class ConversationToolStatus:
    tool_name: str
    status: Literal["started", "succeeded", "failed", "skipped"]
    summary: str


ConversationEvent = ConversationTextDelta | ConversationToolStatus


class Conversation:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry | None = None) -> None:
        self._provider = provider
        self._tools = tools
        self._messages: list[ChatMessage] = []

    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    def ask(self, user_text: str) -> Iterator[ConversationEvent]:
        user_message = ChatMessage(role="user", content=user_text)
        pending_messages = self._messages + [user_message]
        assistant_parts: list[str] = []
        tool_call_event: ProviderToolCall | None = None

        tool_definitions = (
            self._provider.tool_definitions(self._tools) if self._tools is not None else None
        )
        for event in self._provider.stream_reply(pending_messages, tools=tool_definitions):
            if isinstance(event, ProviderTextDelta):
                assistant_parts.append(event.text)
                yield ConversationTextDelta(event.text)
            elif isinstance(event, ProviderToolCall):
                tool_call_event = event
                break

        if tool_call_event is None:
            assistant_text = "".join(assistant_parts)
            self._messages.append(user_message)
            self._messages.append(ChatMessage(role="assistant", content=assistant_text))
            return

        if self._tools is None:
            yield ConversationToolStatus(
                tool_name=tool_call_event.request.name,
                status="skipped",
                summary="tool call requested but no tools are available",
            )
            return

        request = tool_call_event.request
        yield ConversationToolStatus(
            tool_name=request.name,
            status="started",
            summary="running",
        )
        result = self._tools.execute(request)
        yield ConversationToolStatus(
            tool_name=request.name,
            status="succeeded" if result.ok else "failed",
            summary=result.summary(),
        )

        tool_call_message = self._provider.tool_call_message(request)
        tool_result_message = self._provider.tool_result_message(request, result)
        second_messages = pending_messages + [tool_call_message, tool_result_message]
        final_parts: list[str] = []
        for event in self._provider.stream_reply(second_messages, tools=None):
            if isinstance(event, ProviderTextDelta):
                final_parts.append(event.text)
                yield ConversationTextDelta(event.text)
            elif isinstance(event, ProviderToolCall):
                yield ConversationToolStatus(
                    tool_name=event.request.name,
                    status="skipped",
                    summary="tool call limit reached for this turn",
                )
                break

        final_text = "".join(final_parts)
        self._messages.append(user_message)
        self._messages.append(tool_call_message)
        self._messages.append(tool_result_message)
        self._messages.append(ChatMessage(role="assistant", content=final_text))
