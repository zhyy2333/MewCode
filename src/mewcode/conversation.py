from __future__ import annotations

from collections.abc import Iterator

from .providers import ChatMessage, LLMProvider


class Conversation:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._messages: list[ChatMessage] = []

    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    def ask(self, user_text: str) -> Iterator[str]:
        user_message = ChatMessage(role="user", content=user_text)
        pending_messages = self._messages + [user_message]
        assistant_parts: list[str] = []

        for part in self._provider.stream_reply(pending_messages):
            assistant_parts.append(part)
            yield part

        assistant_text = "".join(assistant_parts)
        self._messages.append(user_message)
        self._messages.append(ChatMessage(role="assistant", content=assistant_text))
