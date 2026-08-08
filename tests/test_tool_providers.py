from __future__ import annotations

import asyncio
import json

from mewcode.providers import (
    ChatMessage,
    ModelResponse,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)
from mewcode.providers.anthropic_provider import AnthropicProvider
from mewcode.providers.openai_provider import OpenAIProvider
from mewcode.tools import ToolCallRequest, ToolExecution, ToolResult

from tests.fakes import collect_async
from tests.test_providers import (
    FakeOpenAIEvent,
    install_fake_anthropic,
    install_fake_openai,
    profile,
)


def test_anthropic_multiple_tool_calls_and_bad_json(monkeypatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    client_type.created[0].events = [
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "checking"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tool-1", "name": "read_file"}},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tool-2", "name": "find_files"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":"README.md"}'}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"pattern":'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_stop", "index": 2},
    ]
    events = asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "read")])))

    assert events[0] == ProviderTextDelta("checking")
    calls = [event.request for event in events if isinstance(event, ProviderToolCall)]
    assert calls[0].arguments == {"path": "README.md"}
    assert calls[1].arguments == {}
    assert calls[1].raw_arguments == '{"pattern":'
    assert isinstance(events[-1], ProviderUsage)


def test_anthropic_usage_and_batch_messages(monkeypatch) -> None:
    install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    calls = (
        ToolCallRequest("tool-1", "read_file", {"path": "a"}, '{"path":"a"}'),
        ToolCallRequest("tool-2", "find_files", {"pattern": "*"}, '{"pattern":"*"}'),
    )
    response = ModelResponse("checking", calls, TokenUsage(2, 3, 5))
    assistant = provider.assistant_messages(response)
    assert [block["type"] for block in assistant[0].content] == ["text", "tool_use", "tool_use"]

    executions = [
        ToolExecution(index, call, ToolResult(index == 0, call.name, "ok", None if index == 0 else "bad"))
        for index, call in enumerate(calls)
    ]
    results = provider.tool_result_messages(executions)
    assert [block["tool_use_id"] for block in results[0].content] == ["tool-1", "tool-2"]
    assert json.loads(results[0].content[1]["content"])["error"] == "bad"


def test_openai_multiple_calls_item_done_deduplicates_and_bad_json(monkeypatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    client_type.created[0].events = [
        FakeOpenAIEvent("response.output_item.added", item={"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "read_file"}),
        FakeOpenAIEvent("response.output_item.added", item={"type": "function_call", "id": "fc-2", "call_id": "call-2", "name": "find_files"}),
        FakeOpenAIEvent("response.function_call_arguments.delta", item_id="fc-1", delta='{"path":"README.md"}'),
        FakeOpenAIEvent("response.function_call_arguments.done", item_id="fc-1", arguments='{"path":"README.md"}'),
        FakeOpenAIEvent("response.output_item.done", item={"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "read_file", "arguments": '{"path":"README.md"}'}),
        FakeOpenAIEvent("response.output_item.done", item={"type": "function_call", "id": "fc-2", "call_id": "call-2", "name": "find_files", "arguments": '{"pattern":'}),
    ]
    events = asyncio.run(collect_async(provider.stream_reply([ChatMessage("user", "read")])))
    calls = [event.request for event in events if isinstance(event, ProviderToolCall)]

    assert len(calls) == 2
    assert calls[0].id == "call-1" and calls[0].arguments == {"path": "README.md"}
    assert calls[1].id == "call-2" and calls[1].arguments == {}


def test_openai_usage_and_batch_messages(monkeypatch) -> None:
    install_fake_openai(monkeypatch)
    provider = OpenAIProvider(profile("openai"))
    calls = (
        ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}'),
        ToolCallRequest("call-2", "find_files", {"pattern": "*"}, '{"pattern":"*"}'),
    )
    response = ModelResponse("checking", calls, TokenUsage(2, 3, 5))
    assistant = provider.assistant_messages(response)
    assert assistant[0] == ChatMessage("assistant", "checking")
    assert [message.content["call_id"] for message in assistant[1:]] == ["call-1", "call-2"]

    executions = [
        ToolExecution(index, call, ToolResult(True, call.name, "ok"))
        for index, call in enumerate(calls)
    ]
    results = provider.tool_result_messages(executions)
    assert [message.content["call_id"] for message in results] == ["call-1", "call-2"]
    assert all(message.content["type"] == "function_call_output" for message in results)


def test_provider_parity_and_hidden_reasoning_is_ignored(monkeypatch) -> None:
    anthropic_type = install_fake_anthropic(monkeypatch)
    anthropic = AnthropicProvider(profile("anthropic"))
    anthropic_type.created[0].events = [
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hidden"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "call-1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"path":"a"}'}},
        {"type": "content_block_stop", "index": 2},
    ]
    anthropic_events = asyncio.run(collect_async(anthropic.stream_reply([ChatMessage("user", "x")])))

    openai_type = install_fake_openai(monkeypatch)
    openai = OpenAIProvider(profile("openai"))
    openai_type.created[0].events = [
        FakeOpenAIEvent("response.reasoning_summary_text.delta", delta="hidden"),
        FakeOpenAIEvent("response.output_text.delta", delta="hello"),
        FakeOpenAIEvent("response.output_item.done", item={"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "read_file", "arguments": '{"path":"a"}'}),
    ]
    openai_events = asyncio.run(collect_async(openai.stream_reply([ChatMessage("user", "x")])))

    assert [event for event in anthropic_events if not isinstance(event, ProviderUsage)] == [
        ProviderTextDelta("hello"),
        ProviderToolCall(ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}')),
    ]
    assert [event for event in openai_events if not isinstance(event, ProviderUsage)] == [
        ProviderTextDelta("hello"),
        ProviderToolCall(ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}')),
    ]
