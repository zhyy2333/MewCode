from __future__ import annotations

from typing import Any

from mewcode.conversation import Conversation, ConversationTextDelta, ConversationToolStatus
from mewcode.providers import ChatMessage, ProviderTextDelta, ProviderToolCall
from mewcode.tools import ToolCallRequest, ToolRegistry, ToolResult


class EchoTool:
    name = "echo"
    description = "Echo text."
    parameters_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(ok=True, tool_name=self.name, content=arguments["text"])


class ScriptedProvider:
    def __init__(self, scripts: list[list[object]]) -> None:
        self.scripts = scripts
        self.calls: list[dict[str, Any]] = []

    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        return registry.to_openai_tools()

    def stream_reply(self, messages: list[ChatMessage], tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        script = self.scripts.pop(0)
        yield from script

    def tool_call_message(self, tool_call: ToolCallRequest) -> ChatMessage:
        return ChatMessage(role="assistant", content={"tool_call": tool_call.name})

    def tool_result_message(self, tool_call: ToolCallRequest, result: ToolResult) -> ChatMessage:
        return ChatMessage(
            role="tool",
            content={"tool_call_id": tool_call.id, "ok": result.ok, "error": result.error},
        )


def test_conversation_executes_one_tool_and_generates_final_reply() -> None:
    tool = EchoTool()
    registry = ToolRegistry([tool])
    provider = ScriptedProvider(
        [
            [
                ProviderToolCall(
                    ToolCallRequest(
                        id="call_1",
                        name="echo",
                        arguments={"text": "tool result"},
                        raw_arguments='{"text":"tool result"}',
                    )
                )
            ],
            [ProviderTextDelta("final answer")],
        ]
    )
    conversation = Conversation(provider, tools=registry)

    events = list(conversation.ask("use a tool"))

    assert events == [
        ConversationToolStatus(tool_name="echo", status="started", summary="running"),
        ConversationToolStatus(tool_name="echo", status="succeeded", summary="tool result"),
        ConversationTextDelta("final answer"),
    ]
    assert tool.calls == [{"text": "tool result"}]
    assert provider.calls[0]["tools"][0]["name"] == "echo"
    assert provider.calls[1]["tools"] is None
    assert conversation.messages()[-1] == ChatMessage(role="assistant", content="final answer")


def test_conversation_returns_failed_tool_result_to_provider() -> None:
    provider = ScriptedProvider(
        [
            [
                ProviderToolCall(
                    ToolCallRequest(
                        id="call_1",
                        name="missing",
                        arguments={},
                        raw_arguments="{}",
                    )
                )
            ],
            [ProviderTextDelta("I could not use that tool.")],
        ]
    )
    conversation = Conversation(provider, tools=ToolRegistry([]))

    events = list(conversation.ask("use missing"))

    assert events[1].status == "failed"
    assert "Unknown tool" in events[1].summary
    assert provider.calls[1]["messages"][-1].content["ok"] is False
    assert list(conversation.messages())[-1].content == "I could not use that tool."


def test_conversation_skips_second_tool_call() -> None:
    tool = EchoTool()
    provider = ScriptedProvider(
        [
            [
                ProviderToolCall(
                    ToolCallRequest(
                        id="call_1",
                        name="echo",
                        arguments={"text": "ok"},
                        raw_arguments='{"text":"ok"}',
                    )
                )
            ],
            [
                ProviderToolCall(
                    ToolCallRequest(
                        id="call_2",
                        name="echo",
                        arguments={"text": "second"},
                        raw_arguments='{"text":"second"}',
                    )
                )
            ],
        ]
    )
    conversation = Conversation(provider, tools=ToolRegistry([tool]))

    events = list(conversation.ask("use tools"))

    assert events[-1] == ConversationToolStatus(
        tool_name="echo",
        status="skipped",
        summary="tool call limit reached for this turn",
    )
    assert tool.calls == [{"text": "ok"}]


def test_conversation_with_tools_preserves_no_tool_chat_behavior() -> None:
    tool = EchoTool()
    provider = ScriptedProvider([[ProviderTextDelta("hello"), ProviderTextDelta("!")]])
    conversation = Conversation(provider, tools=ToolRegistry([tool]))

    events = list(conversation.ask("chat"))

    assert events == [ConversationTextDelta("hello"), ConversationTextDelta("!")]
    assert conversation.messages() == [
        ChatMessage(role="user", content="chat"),
        ChatMessage(role="assistant", content="hello!"),
    ]
