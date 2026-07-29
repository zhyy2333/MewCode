from __future__ import annotations

import pytest

from mewcode.conversation import Conversation, ConversationTextDelta
from mewcode.providers import ChatMessage, ProviderError, ProviderTextDelta


class FakeProvider:
    def __init__(self, parts: list[str]) -> None:
        self.parts = parts
        self.calls: list[list[ChatMessage]] = []

    def stream_reply(self, messages: list[ChatMessage], tools=None):
        self.calls.append(list(messages))
        for part in self.parts:
            yield ProviderTextDelta(part)


class FailingProvider:
    def stream_reply(self, messages: list[ChatMessage], tools=None):
        raise ProviderError("request failed")
        yield ""


def test_ask_streams_parts_and_appends_history() -> None:
    provider = FakeProvider(["hel", "lo"])
    conversation = Conversation(provider)

    assert list(conversation.ask("Hi")) == [
        ConversationTextDelta("hel"),
        ConversationTextDelta("lo"),
    ]

    assert provider.calls == [[ChatMessage(role="user", content="Hi")]]
    assert conversation.messages() == [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="hello"),
    ]


def test_messages_returns_copy() -> None:
    provider = FakeProvider(["ok"])
    conversation = Conversation(provider)
    list(conversation.ask("Hi"))

    messages = conversation.messages()
    messages.append(ChatMessage(role="user", content="mutated"))

    assert conversation.messages() == [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="ok"),
    ]


def test_second_turn_includes_previous_context() -> None:
    provider = FakeProvider(["first"])
    conversation = Conversation(provider)
    list(conversation.ask("One"))

    provider.parts = ["second"]
    list(conversation.ask("Two"))

    assert provider.calls[1] == [
        ChatMessage(role="user", content="One"),
        ChatMessage(role="assistant", content="first"),
        ChatMessage(role="user", content="Two"),
    ]


def test_provider_error_does_not_append_partial_history() -> None:
    conversation = Conversation(FailingProvider())

    with pytest.raises(ProviderError):
        list(conversation.ask("Hi"))

    assert conversation.messages() == []
