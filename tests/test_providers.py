from __future__ import annotations

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
    create_provider,
)
from mewcode.providers.anthropic_provider import AnthropicProvider
from mewcode.providers.openai_provider import OpenAIProvider


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
    def __init__(self, parts: list[str]) -> None:
        self.text_stream = parts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeAnthropicMessages:
    def __init__(self, owner: "FakeAnthropicClient") -> None:
        self._owner = owner

    def stream(self, **kwargs):
        self._owner.requests.append(kwargs)
        if self._owner.failures:
            failure = self._owner.failures.pop(0)
            raise failure
        return FakeAnthropicStream(self._owner.parts)


class FakeAnthropicClient:
    created: list["FakeAnthropicClient"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.parts = ["hel", "lo"]
        self.failures: list[Exception] = []
        self.requests: list[dict] = []
        self.messages = FakeAnthropicMessages(self)
        FakeAnthropicClient.created.append(self)


class FakeAnthropicError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> type[FakeAnthropicClient]:
    FakeAnthropicClient.created = []
    module = types.SimpleNamespace(Anthropic=FakeAnthropicClient)
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return FakeAnthropicClient


def test_anthropic_streams_text_and_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))

    parts = list(provider.stream_reply([ChatMessage(role="user", content="Hi")]))

    client = client_type.created[0]
    assert parts == ["hel", "lo"]
    assert client.api_key == "secret-key"
    assert client.base_url == "https://example.test"
    assert client.requests == [
        {
            "model": "model-name",
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": "Hi"}],
        }
    ]


def test_anthropic_sdk_error_is_wrapped_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].failures.append(Exception("bad secret-key"))

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_reply([ChatMessage(role="user", content="Hi")]))

    assert "Anthropic request failed" in exc_info.value.message
    assert "secret-key" not in exc_info.value.message


def test_anthropic_thinking_uses_adaptive_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", thinking=True))

    assert list(provider.stream_reply([ChatMessage(role="user", content="Hi")])) == ["hel", "lo"]

    assert client_type.created[0].requests[0]["thinking"] == {
        "type": "adaptive",
        "display": "omitted",
    }


def test_anthropic_adaptive_unsupported_falls_back_to_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", thinking=True))
    client_type.created[0].failures.append(
        FakeAnthropicError("adaptive thinking is not supported on this model")
    )

    assert list(provider.stream_reply([ChatMessage(role="user", content="Hi")])) == ["hel", "lo"]

    requests = client_type.created[0].requests
    assert requests[0]["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert requests[1]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 1024,
        "display": "omitted",
    }


def test_anthropic_other_error_does_not_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", thinking=True))
    client_type.created[0].failures.append(FakeAnthropicError("other bad request"))

    with pytest.raises(ProviderError):
        list(provider.stream_reply([ChatMessage(role="user", content="Hi")]))

    assert len(client_type.created[0].requests) == 1


@dataclass
class FakeOpenAIEvent:
    type: str
    delta: str = ""
    message: str = ""


class FakeResponses:
    def __init__(self, owner: "FakeOpenAIClient") -> None:
        self._owner = owner

    def create(self, **kwargs):
        self._owner.requests.append(kwargs)
        if self._owner.failure is not None:
            raise self._owner.failure
        return iter(self._owner.events)


class FakeOpenAIClient:
    created: list["FakeOpenAIClient"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.events = [
            FakeOpenAIEvent("response.created"),
            FakeOpenAIEvent("response.output_text.delta", "hel"),
            FakeOpenAIEvent("response.output_text.delta", "lo"),
            FakeOpenAIEvent("response.completed"),
        ]
        self.failure: Exception | None = None
        self.requests: list[dict] = []
        self.responses = FakeResponses(self)
        FakeOpenAIClient.created.append(self)


def install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[FakeOpenAIClient]:
    FakeOpenAIClient.created = []
    module = types.SimpleNamespace(OpenAI=FakeOpenAIClient)
    monkeypatch.setitem(sys.modules, "openai", module)
    return FakeOpenAIClient


def test_openai_streams_only_output_text_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))

    parts = list(
        provider.stream_reply(
            [
                ChatMessage(role="user", content="Hi"),
                ChatMessage(role="assistant", content="Hello"),
            ]
        )
    )

    assert parts == ["hel", "lo"]
    assert client_type.created[0].requests == [
        {
            "model": "model-name",
            "input": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            "max_output_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }
    ]


def test_openai_error_event_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [FakeOpenAIEvent("error", message="rate limited")]

    with pytest.raises(ProviderError, match="rate limited"):
        list(provider.stream_reply([ChatMessage(role="user", content="Hi")]))


def test_openai_sdk_error_is_wrapped_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].failure = Exception("bad secret-key")

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_reply([ChatMessage(role="user", content="Hi")]))

    assert "OpenAI request failed" in exc_info.value.message
    assert "secret-key" not in exc_info.value.message


def test_create_provider_returns_anthropic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_anthropic(monkeypatch)

    provider = create_provider(profile("anthropic"))

    assert isinstance(provider, AnthropicProvider)


def test_create_provider_returns_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_openai(monkeypatch)

    provider = create_provider(profile("openai"))

    assert isinstance(provider, OpenAIProvider)


def test_create_provider_rejects_unknown_protocol() -> None:
    with pytest.raises(ConfigError, match="Unsupported protocol"):
        create_provider(profile("other"))
