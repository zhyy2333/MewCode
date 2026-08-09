from __future__ import annotations

import asyncio
import json

from mewcode.providers import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ProviderFinished,
    ProviderFinishReason,
    ProviderInternalPart,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)
from mewcode.prompting import PromptPackage
from mewcode.providers.anthropic_provider import AnthropicProvider, _anthropic_tools
from mewcode.providers.openai_provider import OpenAIProvider, _openai_tools
from mewcode.tools import ToolCallRequest, ToolExecution, ToolRegistry, ToolResult, ToolSafety

from tests.fakes import collect_async
from tests.test_providers import (
    FakeOpenAIEvent,
    install_fake_anthropic,
    install_fake_openai,
    profile,
)


class _NamedTool:
    description = "test"
    parameters_schema = {"type": "object", "properties": {}}
    safety = ToolSafety.READ_ONLY

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, arguments):
        return ToolResult(True, self.name, "ok")


def test_tool_serialization_is_provider_specific_and_deterministic() -> None:
    first = ToolRegistry([_NamedTool("zeta"), _NamedTool("alpha")])
    second = ToolRegistry([_NamedTool("alpha"), _NamedTool("zeta")])
    assert _anthropic_tools(first) == _anthropic_tools(second)
    assert _openai_tools(first) == _openai_tools(second)
    assert [tool["name"] for tool in _anthropic_tools(first)] == ["alpha", "zeta"]
    assert [tool["name"] for tool in _openai_tools(first)] == ["alpha", "zeta"]
    assert "input_schema" in _anthropic_tools(first)[0]
    assert _openai_tools(first)[0]["type"] == "function"


def test_provider_end_to_end_prompt_parity_keeps_system_history_and_tools_equivalent(
    monkeypatch,
) -> None:
    registry = ToolRegistry([_NamedTool("zeta"), _NamedTool("alpha")])
    model_request = ModelRequest(
        PromptPackage("stable", "dynamic"),
        (ChatMessage("user", "question"),),
        registry,
    )

    anthropic_type = install_fake_anthropic(monkeypatch)
    anthropic = AnthropicProvider(
        profile("anthropic", base_url="https://api.anthropic.com/v1")
    )
    asyncio.run(collect_async(anthropic.stream_reply(model_request)))
    anthropic_request = anthropic_type.created[0].requests[0]

    openai_type = install_fake_openai(monkeypatch)
    openai = OpenAIProvider(
        profile(
            "openai",
            model="gpt-5.6",
            base_url="https://api.openai.com/v1",
        )
    )
    asyncio.run(collect_async(openai.stream_reply(model_request)))
    openai_request = openai_type.created[0].requests[0]

    assert [block["text"] for block in anthropic_request["system"]] == [
        openai_request["input"][0]["content"][0]["text"],
        openai_request["input"][1]["content"][0]["text"],
    ] == ["stable", "dynamic"]
    assert anthropic_request["messages"] == [
        {"role": "user", "content": "question"}
    ]
    assert openai_request["input"][2] == {"role": "user", "content": "question"}
    assert [tool["name"] for tool in anthropic_request["tools"]] == ["alpha", "zeta"]
    assert [tool["name"] for tool in openai_request["tools"]] == ["alpha", "zeta"]


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
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]
    events = asyncio.run(
        collect_async(
            provider.stream_reply(
                ModelRequest(PromptPackage("stable", ""), (ChatMessage("user", "read"),))
            )
        )
    )

    assert events[0] == ProviderTextDelta("checking")
    calls = [event.request for event in events if isinstance(event, ProviderToolCall)]
    assert calls[0].arguments == {"path": "README.md"}
    assert calls[1].arguments == {}
    assert calls[1].raw_arguments == '{"pattern":'
    assert isinstance(events[-2], ProviderUsage)
    assert events[-1] == ProviderFinished(ProviderFinishReason.TOOL_CALLS)


def test_anthropic_usage_and_batch_messages(monkeypatch) -> None:
    install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(profile("anthropic"))
    calls = (
        ToolCallRequest("tool-1", "read_file", {"path": "a"}, '{"path":"a"}'),
        ToolCallRequest("tool-2", "find_files", {"pattern": "*"}, '{"pattern":"*"}'),
    )
    response = ModelResponse(
        "checking", calls, TokenUsage(2, 3, 5), ProviderFinishReason.TOOL_CALLS
    )
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
        FakeOpenAIEvent("response.completed", response={"usage": {}}),
    ]
    events = asyncio.run(
        collect_async(
            provider.stream_reply(
                ModelRequest(PromptPackage("stable", ""), (ChatMessage("user", "read"),))
            )
        )
    )
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
    response = ModelResponse(
        "checking", calls, TokenUsage(2, 3, 5), ProviderFinishReason.TOOL_CALLS
    )
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
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hidden"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "signed"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "call-1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"path":"a"}'}},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]
    anthropic_events = asyncio.run(
        collect_async(
            anthropic.stream_reply(
                ModelRequest(PromptPackage("stable", ""), (ChatMessage("user", "x"),))
            )
        )
    )

    openai_type = install_fake_openai(monkeypatch)
    openai = OpenAIProvider(profile("openai"))
    openai_type.created[0].events = [
        FakeOpenAIEvent("response.reasoning_summary_text.delta", delta="hidden"),
        FakeOpenAIEvent("response.output_item.done", item={"type": "reasoning", "id": "rs-1", "summary": []}),
        FakeOpenAIEvent("response.output_text.delta", delta="hello"),
        FakeOpenAIEvent("response.output_item.done", item={"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "read_file", "arguments": '{"path":"a"}'}),
        FakeOpenAIEvent("response.completed", response={"usage": {}}),
    ]
    openai_events = asyncio.run(
        collect_async(
            openai.stream_reply(
                ModelRequest(PromptPackage("stable", ""), (ChatMessage("user", "x"),))
            )
        )
    )

    assert [
        event
        for event in anthropic_events
        if not isinstance(event, (ProviderUsage, ProviderInternalPart, ProviderFinished))
    ] == [
        ProviderTextDelta("hello"),
        ProviderToolCall(ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}')),
    ]
    assert [
        event
        for event in openai_events
        if not isinstance(event, (ProviderUsage, ProviderInternalPart, ProviderFinished))
    ] == [
        ProviderTextDelta("hello"),
        ProviderToolCall(ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}')),
    ]

    anthropic_internal = next(
        event for event in anthropic_events if isinstance(event, ProviderInternalPart)
    )
    anthropic_response = ModelResponse(
        "hello",
        (ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}'),),
        TokenUsage(),
        ProviderFinishReason.TOOL_CALLS,
        (anthropic_internal,),
    )
    assert anthropic.assistant_messages(anthropic_response)[0].content[0] == {
        "type": "thinking",
        "thinking": "hidden",
        "signature": "signed",
    }

    openai_internal = next(
        event for event in openai_events if isinstance(event, ProviderInternalPart)
    )
    openai_response = ModelResponse(
        "hello",
        (ToolCallRequest("call-1", "read_file", {"path": "a"}, '{"path":"a"}'),),
        TokenUsage(),
        ProviderFinishReason.TOOL_CALLS,
        (openai_internal,),
    )
    messages = openai.assistant_messages(openai_response)
    assert messages[0].content["type"] == "reasoning"
    request = ModelRequest(PromptPackage("stable", ""), tuple(messages))
    assert openai._build_input(request)[1]["type"] == "reasoning"
