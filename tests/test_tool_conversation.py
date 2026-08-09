from __future__ import annotations

import asyncio

from mewcode.agent import (
    AgentStopped,
    AgentToolResult,
    AgentRunner,
    StopReason,
    ToolScheduler,
)
from mewcode.conversation import Conversation
from mewcode.providers import ProviderTextDelta, ProviderToolCall
from mewcode.tools import (
    EditFileTool,
    ReadFileTool,
    RunCommandTool,
    ToolRegistry,
    Workspace,
)

from tests.fakes import (
    AllowAllPermissionController,
    ControlledTool,
    ScriptedAsyncProvider,
    collect_async,
    tool_call,
)


def make_conversation(provider, tools: ToolRegistry) -> Conversation:
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    return Conversation(runner, tools)


def test_react_loop_executes_two_tool_rounds_and_finishes() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call("call-1", "echo", value="one"))],
            [ProviderToolCall(tool_call("call-2", "echo", value="two"))],
            [ProviderTextDelta("final answer")],
        ]
    )
    tool = ControlledTool("echo")
    conversation = make_conversation(provider, ToolRegistry([tool]))

    events = asyncio.run(collect_async(conversation.ask("use tools")))

    assert tool.calls == ["echo", "echo"]
    assert len(provider.calls) == 3
    assert [
        event.execution.request.id
        for event in events
        if isinstance(event, AgentToolResult)
    ] == ["call-1", "call-2"]
    assert events[-1] == AgentStopped(
        "run", 3, StopReason.COMPLETED, "final answer", events[-1].usage, None
    )
    assert conversation.messages()[-1].content["text"] == "final answer"


def test_failed_unknown_tool_result_is_returned_and_loop_continues() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call("call-1", "missing"))],
            [ProviderTextDelta("I recovered.")],
        ]
    )
    conversation = make_conversation(provider, ToolRegistry([]))

    events = asyncio.run(collect_async(conversation.ask("use missing")))

    result = next(event for event in events if isinstance(event, AgentToolResult))
    assert result.execution.result.ok is False
    assert "Unknown tool" in (result.execution.result.error or "")
    assert provider.calls[1].messages[-1].content[0]["ok"] is False
    assert events[-1].reason is StopReason.COMPLETED


def test_no_tool_direct_chat_preserves_multiturn_context() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("hello")], [ProviderTextDelta("again")]]
    )
    conversation = make_conversation(provider, ToolRegistry([ControlledTool("echo")]))

    asyncio.run(collect_async(conversation.ask("first")))
    events = asyncio.run(collect_async(conversation.ask("second")))

    assert events[-1].reason is StopReason.COMPLETED
    assert provider.calls[0].tools is not None
    assert [tool.name for tool in provider.calls[0].tools.list()] == ["echo"]
    assert provider.calls[1].messages[0].content == "first"
    assert len(conversation.messages()) == 4


def test_end_to_end_direct_reads_edits_verifies_and_summarizes(tmp_path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("old", encoding="utf-8")
    workspace = Workspace(tmp_path)
    tools = ToolRegistry(
        [
            ReadFileTool(workspace),
            EditFileTool(workspace),
            RunCommandTool(workspace),
        ]
    )
    provider = ScriptedAsyncProvider(
        [
            [
                ProviderToolCall(
                    tool_call("read", "read_file", path="sample.txt")
                )
            ],
            [
                ProviderToolCall(
                    tool_call(
                        "edit",
                        "edit_file",
                        path="sample.txt",
                        old_text="old",
                        new_text="new",
                    )
                )
            ],
            [
                ProviderToolCall(
                    tool_call(
                        "verify",
                        "run_command",
                        command=(
                            'python -c "from pathlib import Path; '
                            "assert Path('sample.txt').read_text() == 'new'\""
                        ),
                    )
                )
            ],
            [ProviderTextDelta("Updated and verified sample.txt.")],
        ]
    )
    conversation = make_conversation(provider, tools)

    events = asyncio.run(collect_async(conversation.ask("update the file")))

    assert target.read_text(encoding="utf-8") == "new"
    results = [event for event in events if isinstance(event, AgentToolResult)]
    assert [event.execution.request.name for event in results] == [
        "read_file",
        "edit_file",
        "run_command",
    ]
    assert all(event.execution.result.ok for event in results)
    assert events[-1].reason is StopReason.COMPLETED
    assert events[-1].final_text == "Updated and verified sample.txt."
