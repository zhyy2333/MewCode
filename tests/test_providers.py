from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass

import pytest

from mewcode.providers import (
    DEFAULT_MAX_TOKENS,
    ChatMessage,
    ConfigError,
    ProviderError,
    ProviderProfile,
    ProviderTextDelta,
    ProviderUsage,
    TokenUsage,
    create_provider,
)
from mewcode.providers.anthropic_provider import AnthropicProvider
from mewcode.providers.openai_provider import OpenAIProvider

from tests.fakes import collect_async


def profile(protocol: str = "anthropic", thinking: bool = False) -> ProviderProfile:
    return ProviderProfile(
        name="main",
        protocol=protocol,  # type: ignore[arg-type]
        model="model-name",
        base_url="https://example.test",
        api_key="secret-key",
        thinking=thinking,
    )


class FakeAnthropicStream:
    def __init__(self, owner: "FakeAnthropicClient") -> None:
        self._owner = owner
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.closed = True

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._owner.events:
            await asyncio.sleep(0)
            yield event


class FakeAnthropicMessages:
    def __init__(self, owner: "FakeAnthropicClient") -> None:
        self._owner = owner

    def stream(self, **kwargs):
        self._owner.requests.append(kwargs)
        if self._owner.failures:
            raise self._owner.failures.pop(0)
        stream = FakeAnthropicStream(self._owner)
        self._owner.streams.append(stream)
        return stream


class FakeAnthropicClient:
    created: list["FakeAnthropicClient"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.events: list[object] = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hel"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
            {"type": "message_delta", "usage": {"output_tokens": 2}},
        ]
        self.failures: list[Exception] = []
        self.requests: list[dict] = []
        self.streams: list[FakeAnthropicStream] = []
        self.messages = FakeAnthropicMessages(self)
        FakeAnthropicClient.created.append(self)


class FakeAnthropicError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> type[FakeAnthropicClient]:
    FakeAnthropicClient.created = []
    module = types.SimpleNamespace(AsyncAnthropic=FakeAnthropicClient)
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return FakeAnthropicClient


def test_token_usage_adds_and_propagates_unknown() -> None:
    assert TokenUsage(1, 2, 3).add(TokenUsage(4, 5, 9)) == TokenUsage(5, 7, 12)
    assert TokenUsage(1, 2, 3).add(TokenUsage(None, 5, None)) == TokenUsage(None, 7, None)


def test_anthropic_streams_text_usage_and_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    events = asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))

    assert events == [
        ProviderTextDelta("hel"), ProviderTextDelta("lo"),
        ProviderUsage(TokenUsage(3, 2, 5)),
    ]
    client = client_type.created[0]
    assert client.api_key == "secret-key"
    assert client.requests == [{
        "model": "model-name", "max_tokens": DEFAULT_MAX_TOKENS,
        "messages": [{"role": "user", "content": "Hi"}],
    }]


def test_anthropic_sdk_error_is_wrapped_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].failures.append(Exception("bad secret-key"))

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))
    assert "Anthropic request failed" in exc_info.value.message
    assert "secret-key" not in exc_info.value.message


def test_anthropic_thinking_uses_adaptive_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", thinking=True))
    asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))
    assert client_type.created[0].requests[0]["thinking"] == {
        "type": "adaptive", "display": "omitted"
    }


def test_anthropic_adaptive_unsupported_falls_back_to_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", thinking=True))
    client_type.created[0].failures.append(
        FakeAnthropicError("adaptive thinking is not supported on this model")
    )
    asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))
    assert [request["thinking"] for request in client_type.created[0].requests] == [
        {"type": "adaptive", "display": "omitted"},
        {"type": "enabled", "budget_tokens": 1024, "display": "omitted"},
    ]


def test_anthropic_other_error_does_not_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", thinking=True))
    client_type.created[0].failures.append(FakeAnthropicError("other bad request"))
    with pytest.raises(ProviderError):
        asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))
    assert len(client_type.created[0].requests) == 1


@dataclass
class FakeOpenAIEvent:
    type: str
    delta: str = ""
    message: str = ""
    response: object | None = None
    item: object | None = None
    item_id: str = ""
    call_id: str = ""
    arguments: str | None = None
    name: str = ""


class FakeOpenAIStream:
    def __init__(self, owner: "FakeOpenAIClient") -> None:
        self._owner = owner
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._owner.events:
            await asyncio.sleep(0)
            yield event

    async def close(self) -> None:
        self.closed = True


class FakeResponses:
    def __init__(self, owner: "FakeOpenAIClient") -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.requests.append(kwargs)
        if self._owner.failure is not None:
            raise self._owner.failure
        stream = FakeOpenAIStream(self._owner)
        self._owner.streams.append(stream)
        return stream


class FakeOpenAIClient:
    created: list["FakeOpenAIClient"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.events: list[object] = [
            FakeOpenAIEvent("response.created"),
            FakeOpenAIEvent("response.output_text.delta", delta="hel"),
            FakeOpenAIEvent("response.output_text.delta", delta="lo"),
            FakeOpenAIEvent(
                "response.completed",
                response={"usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}},
            ),
        ]
        self.failure: Exception | None = None
        self.requests: list[dict] = []
        self.streams: list[FakeOpenAIStream] = []
        self.responses = FakeResponses(self)
        FakeOpenAIClient.created.append(self)


def install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[FakeOpenAIClient]:
    FakeOpenAIClient.created = []
    module = types.SimpleNamespace(AsyncOpenAI=FakeOpenAIClient)
    monkeypatch.setitem(sys.modules, "openai", module)
    return FakeOpenAIClient


def test_openai_streams_text_usage_and_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    events = asyncio.run(collect_async(provider.stream_reply([
        ChatMessage("user", "Hi"), ChatMessage("assistant", "Hello")
    ])))

    assert events == [
        ProviderTextDelta("hel"), ProviderTextDelta("lo"),
        ProviderUsage(TokenUsage(3, 2, 5)),
    ]
    assert client_type.created[0].requests == [{
        "model": "model-name",
        "input": [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ],
        "max_output_tokens": DEFAULT_MAX_TOKENS,
        "stream": True,
    }]
    assert client_type.created[0].streams[0].closed is True


def test_openai_error_event_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [FakeOpenAIEvent("error", message="rate limited")]
    with pytest.raises(ProviderError, match="rate limited"):
        asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))


def test_openai_sdk_error_is_wrapped_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].failure = Exception("bad secret-key")
    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "Hi")])))
    assert "OpenAI request failed" in exc_info.value.message
    assert "secret-key" not in exc_info.value.message


def test_create_provider_returns_anthropic_provider(monkeypatch) -> None:
    install_fake_anthropic(monkeypatch)
    assert isinstance(create_provider(profile("anthropic")), AnthropicProvider)


def test_create_provider_returns_openai_provider(monkeypatch) -> None:
    install_fake_openai(monkeypatch)
    assert isinstance(create_provider(profile("openai")), OpenAIProvider)


def test_create_provider_rejects_unknown_protocol() -> None:
    with pytest.raises(ConfigError, match="Unsupported protocol"):
        create_provider(profile("other"))
