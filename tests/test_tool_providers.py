from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass

from mewcode.providers import ChatMessage, ProviderTextDelta, ProviderToolCall
from mewcode.providers.anthropic_provider import AnthropicProvider
from mewcode.providers.openai_provider import OpenAIProvider
from mewcode.tools import ToolCallRequest, ToolResult

from tests.test_providers import profile


class FakeAnthropicEventStream:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeAnthropicMessagesWithEvents:
    def __init__(self, owner: "FakeAnthropicClientWithEvents") -> None:
        self._owner = owner

    def stream(self, **kwargs):
        self._owner.requests.append(kwargs)
        return FakeAnthropicEventStream(self._owner.events)


class FakeAnthropicClientWithEvents:
    created: list["FakeAnthropicClientWithEvents"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        self.requests: list[dict] = []
        self.events: list[object] = []
        self.messages = FakeAnthropicMessagesWithEvents(self)
        FakeAnthropicClientWithEvents.created.append(self)


def install_fake_anthropic_events(monkeypatch) -> type[FakeAnthropicClientWithEvents]:
    FakeAnthropicClientWithEvents.created = []
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropicClientWithEvents),
    )
    return FakeAnthropicClientWithEvents


def test_anthropic_parses_text_and_tool_call_events(monkeypatch) -> None:
    client_type = install_fake_anthropic_events(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client = client_type.created[0]
    client.events = [
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "checking"},
        },
        {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '"README.md"}'},
        },
        {"type": "content_block_stop"},
    ]

    events = list(
        provider.stream_reply(
            [ChatMessage(role="user", content="read")],
            tools=[{"name": "read_file", "description": "Read", "input_schema": {}}],
        )
    )

    assert events[0] == ProviderTextDelta("checking")
    assert events[1] == ProviderToolCall(
        ToolCallRequest(
            id="toolu_1",
            name="read_file",
            arguments={"path": "README.md"},
            raw_arguments='{"path":"README.md"}',
        )
    )
    assert client.requests[0]["tools"] == [{"name": "read_file", "description": "Read", "input_schema": {}}]


def test_anthropic_bad_json_yields_empty_arguments_and_raw(monkeypatch) -> None:
    client_type = install_fake_anthropic_events(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].events = [
        {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        },
        {"type": "content_block_stop"},
    ]

    event = list(provider.stream_reply([ChatMessage(role="user", content="read")]))[0]

    assert isinstance(event, ProviderToolCall)
    assert event.request.arguments == {}
    assert event.request.raw_arguments == '{"path":'


def test_anthropic_tool_result_message_contains_json_payload(monkeypatch) -> None:
    install_fake_anthropic_events(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    message = provider.tool_result_message(
        ToolCallRequest(id="toolu_1", name="read_file", arguments={}, raw_arguments="{}"),
        ToolResult(ok=True, tool_name="read_file", content="hello", metadata={"path": "README.md"}),
    )

    assert message.role == "user"
    block = message.content[0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_1"
    assert block["is_error"] is False
    payload = json.loads(block["content"])
    assert payload["ok"] is True
    assert payload["content"] == "hello"


@dataclass
class FakeOpenAIEvent:
    type: str
    item: object | None = None
    call_id: str = ""
    delta: str = ""
    arguments: str | None = None


class FakeOpenAIResponsesWithToolEvents:
    def __init__(self, owner: "FakeOpenAIClientWithToolEvents") -> None:
        self._owner = owner

    def create(self, **kwargs):
        self._owner.requests.append(kwargs)
        return iter(self._owner.events)


class FakeOpenAIClientWithToolEvents:
    created: list["FakeOpenAIClientWithToolEvents"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        self.requests: list[dict] = []
        self.events: list[object] = []
        self.responses = FakeOpenAIResponsesWithToolEvents(self)
        FakeOpenAIClientWithToolEvents.created.append(self)


def install_fake_openai_tool_events(monkeypatch) -> type[FakeOpenAIClientWithToolEvents]:
    FakeOpenAIClientWithToolEvents.created = []
    monkeypatch.setitem(
        sys.modules,
        "openai",
        types.SimpleNamespace(OpenAI=FakeOpenAIClientWithToolEvents),
    )
    return FakeOpenAIClientWithToolEvents


def test_openai_parses_text_and_tool_call_events(monkeypatch) -> None:
    client_type = install_fake_openai_tool_events(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client = client_type.created[0]
    client.events = [
        FakeOpenAIEvent("response.output_text.delta", delta="checking"),
        FakeOpenAIEvent(
            "response.output_item.added",
            item={"type": "function_call", "call_id": "call_1", "name": "read_file"},
        ),
        FakeOpenAIEvent("response.function_call_arguments.delta", call_id="call_1", delta='{"path":'),
        FakeOpenAIEvent(
            "response.function_call_arguments.done",
            call_id="call_1",
            arguments='{"path":"README.md"}',
        ),
    ]

    events = list(
        provider.stream_reply(
            [ChatMessage(role="user", content="read")],
            tools=[{"type": "function", "name": "read_file", "parameters": {}}],
        )
    )

    assert events[0] == ProviderTextDelta("checking")
    assert events[1] == ProviderToolCall(
        ToolCallRequest(
            id="call_1",
            name="read_file",
            arguments={"path": "README.md"},
            raw_arguments='{"path":"README.md"}',
        )
    )
    assert client.requests[0]["tools"] == [{"type": "function", "name": "read_file", "parameters": {}}]


def test_openai_bad_json_yields_empty_arguments_and_raw(monkeypatch) -> None:
    install_fake_openai_tool_events(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    FakeOpenAIClientWithToolEvents.created[0].events = [
        FakeOpenAIEvent(
            "response.output_item.added",
            item={"type": "function_call", "call_id": "call_1", "name": "read_file"},
        ),
        FakeOpenAIEvent(
            "response.function_call_arguments.done",
            call_id="call_1",
            arguments='{"path":',
        ),
    ]

    event = list(provider.stream_reply([ChatMessage(role="user", content="read")]))[0]

    assert isinstance(event, ProviderToolCall)
    assert event.request.arguments == {}
    assert event.request.raw_arguments == '{"path":'


def test_openai_tool_result_message_is_function_call_output(monkeypatch) -> None:
    install_fake_openai_tool_events(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    message = provider.tool_result_message(
        ToolCallRequest(id="call_1", name="read_file", arguments={}, raw_arguments="{}"),
        ToolResult(ok=False, tool_name="read_file", content="", error="missing"),
    )

    assert message.role == "tool"
    assert message.content["type"] == "function_call_output"
    assert message.content["call_id"] == "call_1"
    payload = json.loads(message.content["output"])
    assert payload["ok"] is False
    assert payload["error"] == "missing"


def test_openai_build_input_preserves_tool_result_item(monkeypatch) -> None:
    install_fake_openai_tool_events(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    message = ChatMessage(
        role="tool",
        content={"type": "function_call_output", "call_id": "call_1", "output": "{}"},
    )

    assert provider._build_input([message]) == [
        {"type": "function_call_output", "call_id": "call_1", "output": "{}"}
    ]
