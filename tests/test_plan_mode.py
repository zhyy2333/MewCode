from __future__ import annotations

import asyncio

import pytest

from mewcode.agent import AgentRunner, AgentTokenUsage, StopReason, ToolScheduler
from mewcode.conversation import Conversation, ConversationError, PendingPlan
from mewcode.providers import (
    ProviderError,
    ProviderFinished,
    ProviderFinishReason,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)
from mewcode.tools import ToolRegistry, ToolSafety, Workspace, create_builtin_registry

from tests.fakes import (
    ControlledTool,
    ScriptedAsyncProvider,
    collect_async,
    tool_call,
)


TOOL_NAMES = [
    "read_file", "write_file", "edit_file", "run_command", "find_files", "search_code"
]


def registry() -> ToolRegistry:
    readonly = {"read_file", "find_files", "search_code"}
    return ToolRegistry(
        [
            ControlledTool(
                name,
                ToolSafety.READ_ONLY if name in readonly else ToolSafety.SIDE_EFFECT,
            )
            for name in TOOL_NAMES
        ]
    )


def conversation(provider) -> Conversation:
    return Conversation(
        AgentRunner(provider, ToolScheduler(), id_factory=lambda: "run"),
        registry(),
    )


def test_plan_uses_readonly_tools_and_saves_text() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("investigation complete")], [ProviderTextDelta("the plan")]]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("build it")))

    assert [tool["name"] for tool in provider.calls[0]["tools"]] == [
        "read_file", "find_files", "search_code"
    ]
    assert provider.calls[0]["max_output_tokens"] == 4096
    assert provider.calls[1]["tools"] is None
    assert provider.calls[1]["max_output_tokens"] == 8192
    assert session.pending_plan() == PendingPlan("build it", "the plan")
    assert "Do not make changes" in provider.calls[0]["messages"][-1].content


def test_new_successful_plan_replaces_old_plan() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("draft one")],
            [ProviderTextDelta("first")],
            [ProviderTextDelta("draft two")],
            [ProviderTextDelta("second")],
        ]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("one")))
    asyncio.run(collect_async(session.plan("two")))
    assert session.pending_plan() == PendingPlan("two", "second")


def test_failed_plan_keeps_previous_plan() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("draft")],
            [ProviderTextDelta("first")],
            ProviderError("failed"),
        ]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("one")))
    events = asyncio.run(collect_async(session.plan("two")))

    assert events[-1].reason is StopReason.STREAM_ERROR
    assert session.pending_plan() == PendingPlan("one", "first")


def test_execute_completed_uses_all_tools_and_clears_plan() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("draft")],
            [ProviderTextDelta("the plan")],
            [ProviderTextDelta("done")],
        ]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("build it")))
    events = asyncio.run(collect_async(session.execute_plan()))

    assert events[-1].reason is StopReason.COMPLETED
    assert [tool["name"] for tool in provider.calls[2]["tools"]] == TOOL_NAMES
    assert "Approved plan:\nthe plan" in provider.calls[2]["messages"][-1].content
    assert session.pending_plan() is None


def test_execute_failure_keeps_plan_for_retry() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("draft")],
            [ProviderTextDelta("the plan")],
            ProviderError("failed"),
            [ProviderTextDelta("done")],
        ]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("build it")))
    events = asyncio.run(collect_async(session.execute_plan()))
    assert events[-1].reason is StopReason.STREAM_ERROR
    assert session.pending_plan() == PendingPlan("build it", "the plan")

    asyncio.run(collect_async(session.execute_plan()))
    assert session.pending_plan() is None


def test_empty_plan_and_missing_execute_do_not_call_provider() -> None:
    provider = ScriptedAsyncProvider([])
    session = conversation(provider)
    with pytest.raises(ConversationError, match="Usage"):
        asyncio.run(collect_async(session.plan(" ")))
    with pytest.raises(ConversationError, match="No pending plan"):
        asyncio.run(collect_async(session.execute_plan()))
    assert provider.calls == []


def test_end_to_end_plan_then_do_reads_writes_verifies_and_clears(tmp_path) -> None:
    (tmp_path / "input.txt").write_text("source", encoding="utf-8")
    provider = ScriptedAsyncProvider(
        [
            [
                ProviderToolCall(
                    tool_call("inspect", "read_file", path="input.txt")
                )
            ],
            [ProviderTextDelta("Write output.txt, then verify it.")],
            [ProviderTextDelta("Write output.txt, then verify it.")],
            [
                ProviderToolCall(
                    tool_call(
                        "write",
                        "write_file",
                        path="output.txt",
                        content="complete",
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
                            "assert Path('output.txt').read_text() == 'complete'\""
                        ),
                    )
                )
            ],
            [ProviderTextDelta("Plan executed and verified.")],
        ]
    )
    tools = create_builtin_registry(Workspace(tmp_path))
    session = Conversation(
        AgentRunner(provider, ToolScheduler(), id_factory=lambda: "run"), tools
    )

    plan_events = asyncio.run(collect_async(session.plan("produce the output")))
    execute_events = asyncio.run(collect_async(session.execute_plan()))

    assert plan_events[-1].reason is StopReason.COMPLETED
    assert [tool["name"] for tool in provider.calls[0]["tools"]] == [
        "read_file",
        "find_files",
        "search_code",
    ]
    assert provider.calls[2]["tools"] is None
    assert provider.calls[2]["max_output_tokens"] == 8192
    assert [tool["name"] for tool in provider.calls[3]["tools"]] == TOOL_NAMES
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "complete"
    assert execute_events[-1].reason is StopReason.COMPLETED
    assert session.pending_plan() is None

    call_count = len(provider.calls)
    with pytest.raises(ConversationError, match="No pending plan"):
        asyncio.run(collect_async(session.execute_plan()))
    assert len(provider.calls) == call_count


def test_plan_executes_sixth_investigation_then_finalizes_once() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderToolCall(tool_call(f"inspect-{index}", "read_file"))]
            for index in range(1, 7)
        ]
        + [[ProviderTextDelta("final plan")]]
    )
    tools = registry()
    session = Conversation(
        AgentRunner(provider, ToolScheduler(), id_factory=lambda: "run"), tools
    )

    events = asyncio.run(collect_async(session.plan("build it")))

    assert events[-1].reason is StopReason.COMPLETED
    assert len(provider.calls) == 7
    assert all(call["tools"] is not None for call in provider.calls[:6])
    assert provider.calls[6]["tools"] is None
    assert provider.calls[6]["max_output_tokens"] == 8192
    read_tool = tools.get("read_file")
    assert read_tool is not None
    assert read_tool.calls == ["read_file"] * 6
    assert session.pending_plan() == PendingPlan("build it", "final plan")


def test_final_output_limit_keeps_previous_plan() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("old draft")],
            [ProviderTextDelta("old plan")],
            [ProviderTextDelta("new draft")],
            [
                ProviderTextDelta("partial"),
                ProviderFinished(ProviderFinishReason.OUTPUT_LIMIT),
            ],
        ]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("old task")))

    events = asyncio.run(collect_async(session.plan("new task")))

    assert events[-1].reason is StopReason.OUTPUT_LIMIT
    assert session.pending_plan() == PendingPlan("old task", "old plan")


def test_final_empty_response_does_not_create_plan() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("draft")], [ProviderTextDelta("   ")]]
    )
    session = conversation(provider)

    events = asyncio.run(collect_async(session.plan("build it")))

    assert events[-1].reason is StopReason.EMPTY_RESPONSE
    assert session.pending_plan() is None


def test_investigation_error_does_not_start_finalization() -> None:
    provider = ScriptedAsyncProvider([ProviderError("failed")])
    session = conversation(provider)

    events = asyncio.run(collect_async(session.plan("build it")))

    assert events[-1].reason is StopReason.STREAM_ERROR
    assert len(provider.calls) == 1
    assert session.pending_plan() is None


def test_investigation_output_limit_does_not_start_finalization() -> None:
    provider = ScriptedAsyncProvider(
        [[
            ProviderTextDelta("partial investigation"),
            ProviderFinished(ProviderFinishReason.OUTPUT_LIMIT),
        ]]
    )
    session = conversation(provider)

    events = asyncio.run(collect_async(session.plan("build it")))

    assert events[-1].reason is StopReason.OUTPUT_LIMIT
    assert len(provider.calls) == 1
    assert session.pending_plan() is None


def test_finalization_tool_call_is_not_executed() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("draft")],
            [ProviderToolCall(tool_call("unexpected", "read_file"))],
        ]
    )
    tools = registry()
    session = Conversation(
        AgentRunner(provider, ToolScheduler(), id_factory=lambda: "run"), tools
    )

    events = asyncio.run(collect_async(session.plan("build it")))

    assert events[-1].reason is StopReason.ERROR
    assert "tools were disabled" in (events[-1].error or "")
    read_tool = tools.get("read_file")
    assert read_tool is not None
    assert read_tool.calls == []
    assert session.pending_plan() is None


def test_finalization_stream_error_keeps_previous_plan() -> None:
    provider = ScriptedAsyncProvider(
        [
            [ProviderTextDelta("old draft")],
            [ProviderTextDelta("old plan")],
            [ProviderTextDelta("new draft")],
            ProviderError("failed during finalization"),
        ]
    )
    session = conversation(provider)
    asyncio.run(collect_async(session.plan("old task")))

    events = asyncio.run(collect_async(session.plan("new task")))

    assert events[-1].reason is StopReason.STREAM_ERROR
    assert session.pending_plan() == PendingPlan("old task", "old plan")


def test_plan_two_stages_share_run_and_accumulate_usage() -> None:
    provider = ScriptedAsyncProvider(
        [
            [
                ProviderTextDelta("draft"),
                ProviderUsage(TokenUsage(2, 3, 5)),
            ],
            [
                ProviderTextDelta("final plan"),
                ProviderUsage(TokenUsage(7, 11, 18)),
            ],
        ]
    )
    session = conversation(provider)

    events = asyncio.run(collect_async(session.plan("build it")))

    usage_events = [event for event in events if isinstance(event, AgentTokenUsage)]
    assert [event.run_id for event in usage_events] == ["run", "run"]
    assert usage_events[-1].cumulative == TokenUsage(9, 14, 23)
    assert events[-1].usage == TokenUsage(9, 14, 23)
