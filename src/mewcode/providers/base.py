from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from typing import Any, Literal, Protocol as TypingProtocol

from mewcode.tools import ToolCallRequest, ToolExecution, ToolRegistry

Protocol = Literal["anthropic", "openai"]
ChatRole = str

DEFAULT_MAX_TOKENS = 4096


class ThinkingMode(StrEnum):
    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"


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
    thinking: bool | str | None = None


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    protocol: Protocol
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingMode = ThinkingMode.AUTO


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


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def zero(cls) -> TokenUsage:
        return cls(input_tokens=0, output_tokens=0, total_tokens=0)

    def add(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=_add_optional(self.input_tokens, other.input_tokens),
            output_tokens=_add_optional(self.output_tokens, other.output_tokens),
            total_tokens=_add_optional(self.total_tokens, other.total_tokens),
        )


class LLMProvider(TypingProtocol):
    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        ...

    def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_output_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[ProviderEvent]:
        ...

    def assistant_messages(self, response: ModelResponse) -> list[ChatMessage]:
        ...

    def tool_result_messages(
        self, executions: Sequence[ToolExecution]
    ) -> list[ChatMessage]:
        ...


@dataclass(frozen=True)
class ProviderTextDelta:
    text: str


@dataclass(frozen=True)
class ProviderToolCall:
    request: ToolCallRequest


@dataclass(frozen=True)
class ProviderUsage:
    usage: TokenUsage


class ProviderFinishReason(StrEnum):
    NATURAL = "natural"
    TOOL_CALLS = "tool_calls"
    OUTPUT_LIMIT = "output_limit"


@dataclass(frozen=True)
class ProviderFinished:
    reason: ProviderFinishReason


@dataclass(frozen=True)
class ProviderInternalPart:
    data: Any = field(repr=False)


ProviderEvent = (
    ProviderTextDelta
    | ProviderToolCall
    | ProviderUsage
    | ProviderFinished
    | ProviderInternalPart
)


@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCallRequest, ...]
    usage: TokenUsage
    finish_reason: ProviderFinishReason
    internal_parts: tuple[ProviderInternalPart, ...] = ()


def _add_optional(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left + right


def create_provider(profile: ProviderProfile) -> LLMProvider:
    if profile.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(profile)
    if profile.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(profile)
    raise ConfigError(f"Unsupported protocol: {profile.protocol}")
