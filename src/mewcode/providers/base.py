from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal, Protocol as TypingProtocol

Protocol = Literal["anthropic", "openai"]
ChatRole = Literal["user", "assistant"]

DEFAULT_MAX_TOKENS = 4096


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


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
    def stream_reply(self, messages: list[ChatMessage]) -> Iterator[str]:
        ...


def create_provider(profile: ProviderProfile) -> LLMProvider:
    if profile.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(profile)
    if profile.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(profile)
    raise ConfigError(f"Unsupported protocol: {profile.protocol}")
