from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Literal, Protocol as TypingProtocol

from mewcode.tools import ToolCallRequest, ToolRegistry, ToolResult

Protocol = Literal["anthropic", "openai"]
ChatRole = str

DEFAULT_MAX_TOKENS = 4096


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: Any


@dataclass(frozen=True)
class RawProviderProfile:
    name: str
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: bool = False


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    protocol: Protocol
    model: str
    base_url: str
    api_key: str
    thinking: bool = False


@dataclass(frozen=True)
class AppConfig:
    active: str
    profiles: list[RawProviderProfile]


class MewCodeError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ConfigError(MewCodeError):
    pass


class ProviderError(MewCodeError):
    pass


class LLMProvider(TypingProtocol):
    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        ...

    def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ProviderEvent]:
        ...

    def tool_result_message(
        self,
        tool_call: ToolCallRequest,
        result: ToolResult,
    ) -> ChatMessage:
        ...

    def tool_call_message(self, tool_call: ToolCallRequest) -> ChatMessage:
        ...


@dataclass(frozen=True)
class ProviderTextDelta:
    text: str


@dataclass(frozen=True)
class ProviderToolCall:
    request: ToolCallRequest


ProviderEvent = ProviderTextDelta | ProviderToolCall


def create_provider(profile: ProviderProfile) -> LLMProvider:
    if profile.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(profile)
    if profile.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(profile)
    raise ConfigError(f"Unsupported protocol: {profile.protocol}")
