from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass

import pytest

from mewcode.prompting import PromptPackage
from mewcode.providers import (
    DEFAULT_MAX_TOKENS,
    ChatMessage,
    ConfigError,
    ModelRequest,
    ProviderError,
    ProviderFinished,
    ProviderFinishReason,
    ProviderProfile,
    ProviderTextDelta,
    ProviderUsage,
    TokenUsage,
    ThinkingMode,
    create_provider,
)
from mewcode.tools import ToolRegistry
from mewcode.providers.anthropic_provider import AnthropicProvider
from mewcode.providers.openai_provider import OpenAIProvider

from tests.fakes import collect_async


def profile(
    protocol: str = "anthropic",
    thinking: ThinkingMode = ThinkingMode.AUTO,
    *,
    model: str = "model-name",
    base_url: str = "https://example.test",
) -> ProviderProfile:
    return ProviderProfile(
        name="main",
        protocol=protocol,  # type: ignore[arg-type]
        model=model,
        base_url=base_url,
        api_key="secret-key",
        thinking=thinking,
    )


def model_request(
    *messages: ChatMessage,
    stable: str = "stable instructions",
    dynamic: str = "dynamic context",
    tools: ToolRegistry | None = None,
    max_output_tokens: int = DEFAULT_MAX_TOKENS,
) -> ModelRequest:
    return ModelRequest(
        prompt=PromptPackage(stable, dynamic),
        messages=tuple(messages),
        tools=tools,
        max_output_tokens=max_output_tokens,
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
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            },
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


def test_model_request_uses_immutable_messages_and_registry() -> None:
    registry = ToolRegistry([])
    request = ModelRequest(
        prompt=PromptPackage("stable", "dynamic"),
        messages=(ChatMessage("user", "hello"),),
        tools=registry,
        max_output_tokens=123,
    )
    assert request.messages == (ChatMessage("user", "hello"),)
    assert isinstance(request.messages, tuple)
    assert request.tools is registry
    assert request.max_output_tokens == 123


def test_cache_usage_adds_and_propagates_unknown() -> None:
    assert TokenUsage(1, 2, 3, 4, 5).add(TokenUsage(6, 7, 13, 8, 9)) == TokenUsage(
        7, 9, 16, 12, 14
    )
    assert TokenUsage(1, 2, 3, None, 0).add(TokenUsage(1, 2, 3, 5, 0)) == TokenUsage(
        2, 4, 6, None, 0
    )
    assert TokenUsage.zero() == TokenUsage(0, 0, 0, 0, 0, 0)


def test_anthropic_system_blocks_cache_breakpoint_uses_official_boundary(
    monkeypatch,
) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(
        profile("anthropic", base_url="https://api.anthropic.com/v1")
    )
    asyncio.run(
        collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
    )
    request = client_type.created[0].requests[0]
    assert request["system"] == [
        {
            "type": "text",
            "text": "stable instructions",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "dynamic context"},
    ]
    assert request["messages"] == [{"role": "user", "content": "Hi"}]


def test_anthropic_compatible_host_uses_plain_system(monkeypatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    asyncio.run(
        collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
    )
    request = client_type.created[0].requests[0]
    assert request["system"] == "stable instructions\n\ndynamic context"
    assert "cache_control" not in request


def test_anthropic_cache_usage_is_normalized(monkeypatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].events = [
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 7,
                    "cache_creation_input_tokens": 3,
                }
            },
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 2},
        },
    ]
    events = asyncio.run(
        collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
    )
    assert ProviderUsage(TokenUsage(10, 2, 12, 7, 3, 20)) in events


def test_openai_system_input_and_explicit_cache(monkeypatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(
        profile(
            "openai",
            model="gpt-5.6-terra",
            base_url="https://api.openai.com/v1",
        )
    )
    asyncio.run(
        collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
    )
    request = client_type.created[0].requests[0]
    assert request["input"][:2] == [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": "stable instructions",
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ],
        },
        {
            "role": "system",
            "content": [{"type": "input_text", "text": "dynamic context"}],
        },
    ]
    assert request["input"][2] == {"role": "user", "content": "Hi"}
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert request["prompt_cache_key"].startswith("mewcode:")


def test_openai_cache_key_ignores_dynamic_content_and_changes_with_stable(monkeypatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(
        profile("openai", model="gpt-5.6", base_url="https://api.openai.com/v1")
    )
    asyncio.run(
        collect_async(
            provider.stream_reply(
                model_request(ChatMessage("user", "one"), dynamic="first")
            )
        )
    )
    asyncio.run(
        collect_async(
            provider.stream_reply(
                model_request(ChatMessage("user", "two"), dynamic="second")
            )
        )
    )
    asyncio.run(
        collect_async(
            provider.stream_reply(
                model_request(ChatMessage("user", "two"), stable="changed")
            )
        )
    )
    keys = [request["prompt_cache_key"] for request in client_type.created[0].requests]
    assert keys[0] == keys[1]
    assert keys[1] != keys[2]
    assert "stable instructions" not in keys[0]


@pytest.mark.parametrize(
    ("model", "base_url"),
    [
        ("gpt-5.5", "https://api.openai.com/v1"),
        ("gpt-5.6", "https://compatible.example/v1"),
    ],
)
def test_openai_automatic_cache_fallback_omits_explicit_fields(
    monkeypatch, model: str, base_url: str
) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(
        profile("openai", model=model, base_url=base_url)
    )
    asyncio.run(
        collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
    )
    request = client_type.created[0].requests[0]
    assert "prompt_cache_options" not in request
    assert "prompt_cache_key" not in request
    assert "prompt_cache_breakpoint" not in request["input"][0]["content"][0]


def test_openai_cache_usage_is_normalized(monkeypatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [
        FakeOpenAIEvent(
            "response.completed",
            response={
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "input_tokens_details": {
                        "cached_tokens": 7,
                        "cache_write_tokens": 3,
                    },
                }
            },
        )
    ]
    events = asyncio.run(
        collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
    )
    assert ProviderUsage(TokenUsage(10, 2, 12, 7, 3, 10)) in events


def test_anthropic_streams_text_usage_and_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    events = asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))

    assert events == [
        ProviderTextDelta("hel"), ProviderTextDelta("lo"),
        ProviderUsage(TokenUsage(3, 2, 5, None, None, 3)),
        ProviderFinished(ProviderFinishReason.NATURAL),
    ]
    client = client_type.created[0]
    assert client.api_key == "secret-key"
    assert client.requests == [{
        "model": "model-name", "max_tokens": DEFAULT_MAX_TOKENS,
        "messages": [{"role": "user", "content": "Hi"}],
        "system": "stable instructions\n\ndynamic context",
    }]


def test_anthropic_uses_per_call_output_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))

    asyncio.run(
        collect_async(
            provider.stream_reply(model_request(ChatMessage("user", "Hi"), max_output_tokens=8192))
        )
    )

    assert client_type.created[0].requests[0]["max_tokens"] == 8192


def test_anthropic_sdk_error_is_wrapped_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].failures.append(Exception("bad secret-key"))

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert "Anthropic request failed" in exc_info.value.message
    assert "secret-key" not in exc_info.value.message


def test_anthropic_thinking_uses_adaptive_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", ThinkingMode.ENABLED))
    asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert client_type.created[0].requests[0]["thinking"] == {
        "type": "adaptive", "display": "omitted"
    }


def test_anthropic_adaptive_unsupported_falls_back_to_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", ThinkingMode.ENABLED))
    client_type.created[0].failures.append(
        FakeAnthropicError("adaptive thinking is not supported on this model")
    )
    asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert [request["thinking"] for request in client_type.created[0].requests] == [
        {"type": "adaptive", "display": "omitted"},
        {"type": "enabled", "budget_tokens": 1024, "display": "omitted"},
    ]


def test_anthropic_other_error_does_not_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", ThinkingMode.ENABLED))
    client_type.created[0].failures.append(FakeAnthropicError("other bad request"))
    with pytest.raises(ProviderError):
        asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert len(client_type.created[0].requests) == 1


def test_anthropic_thinking_disabled_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic", ThinkingMode.DISABLED))
    asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert client_type.created[0].requests[0]["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", ProviderFinishReason.NATURAL),
        ("stop_sequence", ProviderFinishReason.NATURAL),
        ("tool_use", ProviderFinishReason.TOOL_CALLS),
        ("max_tokens", ProviderFinishReason.OUTPUT_LIMIT),
    ],
)
def test_anthropic_finish_reason_mapping(
    monkeypatch: pytest.MonkeyPatch,
    stop_reason: str,
    expected: ProviderFinishReason,
) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].events = [
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}}
    ]

    events = asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert events[-1] == ProviderFinished(expected)


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


@pytest.mark.parametrize("protocol", ["anthropic", "openai"])
def test_provider_end_to_end_maps_prompt_stream_and_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
) -> None:
    if protocol == "anthropic":
        client_type = install_fake_anthropic(monkeypatch)
        provider = AnthropicProvider(
            profile("anthropic", base_url="https://api.anthropic.com/v1")
        )
        client_type.created[0].events = [
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 7,
                        "cache_creation_input_tokens": 3,
                    }
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "answer"},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            },
        ]
    else:
        client_type = install_fake_openai(monkeypatch)
        provider = OpenAIProvider(
            profile(
                "openai",
                model="gpt-5.6",
                base_url="https://api.openai.com/v1",
            )
        )
        client_type.created[0].events = [
            FakeOpenAIEvent("response.output_text.delta", delta="answer"),
            FakeOpenAIEvent(
                "response.completed",
                response={
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "total_tokens": 12,
                        "input_tokens_details": {
                            "cached_tokens": 7,
                            "cache_write_tokens": 3,
                        },
                    }
                },
            ),
        ]

    events = asyncio.run(
        collect_async(
            provider.stream_reply(model_request(ChatMessage("user", "question")))
        )
    )
    request = client_type.created[0].requests[0]

    expected_context_input = 20 if protocol == "anthropic" else 10
    assert events == [
        ProviderTextDelta("answer"),
        ProviderUsage(TokenUsage(10, 2, 12, 7, 3, expected_context_input)),
        ProviderFinished(ProviderFinishReason.NATURAL),
    ]
    if protocol == "anthropic":
        assert request["system"][0]["text"] == "stable instructions"
        assert request["system"][1]["text"] == "dynamic context"
        assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    else:
        assert request["input"][0]["content"][0]["text"] == "stable instructions"
        assert request["input"][1]["content"][0]["text"] == "dynamic context"
        assert request["prompt_cache_options"] == {"mode": "explicit"}


def test_openai_streams_text_usage_and_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    events = asyncio.run(collect_async(provider.stream_reply(model_request(
        ChatMessage("user", "Hi"), ChatMessage("assistant", "Hello")
    ))))

    assert events == [
        ProviderTextDelta("hel"), ProviderTextDelta("lo"),
        ProviderUsage(TokenUsage(3, 2, 5, None, None, 3)),
        ProviderFinished(ProviderFinishReason.NATURAL),
    ]
    assert client_type.created[0].requests == [{
        "model": "model-name",
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": "stable instructions"}],
            },
            {
                "role": "system",
                "content": [{"type": "input_text", "text": "dynamic context"}],
            },
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ],
        "max_output_tokens": DEFAULT_MAX_TOKENS,
        "stream": True,
    }]
    assert client_type.created[0].streams[0].closed is True


def test_openai_uses_per_call_output_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))

    asyncio.run(
        collect_async(
            provider.stream_reply(model_request(ChatMessage("user", "Hi"), max_output_tokens=8192))
        )
    )

    assert client_type.created[0].requests[0]["max_output_tokens"] == 8192


@pytest.mark.parametrize(
    ("thinking", "reasoning"),
    [
        (ThinkingMode.AUTO, None),
        (ThinkingMode.ENABLED, {"effort": "medium"}),
        (ThinkingMode.DISABLED, {"effort": "none"}),
    ],
)
def test_openai_thinking_mode_mapping(
    monkeypatch: pytest.MonkeyPatch,
    thinking: ThinkingMode,
    reasoning: dict | None,
) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai", thinking))
    asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    request = client_type.created[0].requests[0]
    if reasoning is None:
        assert "reasoning" not in request
    else:
        assert request["reasoning"] == reasoning


def test_openai_incomplete_max_output_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [
        FakeOpenAIEvent(
            "response.incomplete",
            response={
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {"input_tokens": 4, "output_tokens": 9, "total_tokens": 13},
            },
        )
    ]

    events = asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
    assert events == [
        ProviderUsage(TokenUsage(4, 9, 13, None, None, 4)),
        ProviderFinished(ProviderFinishReason.OUTPUT_LIMIT),
    ]


def test_openai_failed_response_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [
        FakeOpenAIEvent(
            "response.failed",
            response={"error": {"message": "generation failed"}},
        )
    ]

    with pytest.raises(ProviderError, match="generation failed"):
        asyncio.run(
            collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi"))))
        )


def test_openai_error_event_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [FakeOpenAIEvent("error", message="rate limited")]
    with pytest.raises(ProviderError, match="rate limited"):
        asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))


def test_openai_sdk_error_is_wrapped_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].failure = Exception("bad secret-key")
    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(collect_async(provider.stream_reply(model_request(ChatMessage("user", "Hi")))))
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
