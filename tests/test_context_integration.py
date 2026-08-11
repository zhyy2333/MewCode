from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from mewcode.agent import AgentContextStatus, AgentRunner, ToolScheduler
from mewcode.context import ContextArchive, ContextConfig, ContextManager, ContextStatusKind
from mewcode.conversation import Conversation
from mewcode.providers import ChatMessage, MessageKind, ModelResponse, ProviderTextDelta, ProviderToolCall
from mewcode.tools import ToolExecution, ToolRegistry, ToolResult

from tests.fakes import (
    AllowAllPermissionController,
    ControlledTool,
    ScriptedAsyncProvider,
    collect_async,
    tool_call,
)


class ProtocolShapeProvider(ScriptedAsyncProvider):
    def __init__(self, style: str, scripts) -> None:
        super().__init__(scripts)
        self.style = style

    def assistant_messages(
        self,
        response: ModelResponse,
        group_id: str | None = None,
    ) -> list[ChatMessage]:
        if self.style == "openai":
            return super().assistant_messages(response, group_id)
        content = [{"type": "text", "text": response.text}] if response.text else []
        content.extend(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.arguments,
            }
            for call in response.tool_calls
        )
        return [
            ChatMessage(
                "assistant",
                content,
                MessageKind.TOOL_CALL if response.tool_calls else MessageKind.ASSISTANT,
                group_id,
            )
        ]

    def tool_result_messages(
        self,
        executions: Sequence[ToolExecution],
        group_id: str | None = None,
    ) -> list[ChatMessage]:
        if self.style == "openai":
            return super().tool_result_messages(executions, group_id)
        return [
            ChatMessage(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": execution.request.id,
                        "content": execution.result.content,
                    }
                    for execution in executions
                ],
                MessageKind.TOOL_RESULT,
                group_id,
            )
        ]


def summary_response(path: str) -> str:
    titles = (
        "当前目标",
        "仍有效的用户原始约束",
        "关键决策及理由",
        "已完成工作",
        "当前代码与文件状态",
        "未解决问题与风险",
        "下一步行动",
        "存盘记录索引",
    )
    body = "\n\n".join(
        f"## {index}. {title}\n{path if index == 8 else '无'}"
        for index, title in enumerate(titles, start=1)
    )
    return (
        "<analysis_draft>private draft</analysis_draft>"
        f"<formal_summary>{body}</formal_summary>"
    )


@pytest.mark.parametrize("style", ["openai", "anthropic"])
def test_long_conversation_parity_tool_pairing_preflight_order_and_boundary(
    tmp_path: Path,
    style: str,
) -> None:
    call = tool_call("call-1", "large")
    large_answer = "a" * 55_000
    path = ".mewcode/context/session/history-000002.json"
    provider = ProtocolShapeProvider(
        style,
        [
            [ProviderToolCall(call)],
            [ProviderTextDelta(large_answer)],
            [ProviderTextDelta(large_answer)],
            [ProviderTextDelta(large_answer)],
            [ProviderTextDelta(large_answer)],
            [ProviderTextDelta(summary_response(path))],
            [ProviderTextDelta("done")],
        ],
    )
    tool = ControlledTool(
        "large",
        result=ToolResult(True, "large", "HEAD" + "x" * 40_000 + "TAIL"),
    )
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
    archive.start()
    manager = ContextManager(provider, archive, ContextConfig(70_000))
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
        context_manager=manager,
    )
    conversation = Conversation(
        runner,
        ToolRegistry([tool]),
        context_manager=manager,
    )

    first_events = asyncio.run(collect_async(conversation.ask("first")))
    for index in range(2, 5):
        asyncio.run(collect_async(conversation.ask(f"turn-{index}")))
    final_events = asyncio.run(collect_async(conversation.ask("finish")))

    first_statuses = {
        event.status.kind
        for event in first_events
        if isinstance(event, AgentContextStatus)
    }
    final_statuses = {
        event.status.kind
        for event in final_events
        if isinstance(event, AgentContextStatus)
    }
    messages = conversation.messages()
    assert ContextStatusKind.TOOL_ARCHIVED in first_statuses
    assert ContextStatusKind.COMPACTION_COMPLETED in final_statuses
    assert len(provider.calls) == 7
    assert provider.calls[5].tools is None
    assert provider.calls[5].max_output_tokens == 8_192
    assert messages[0].kind is MessageKind.SUMMARY
    assert messages[1].kind is MessageKind.BOUNDARY
    assert all("private draft" not in str(message.content) for message in messages)
    assert messages[-1].content != "finish"
    assert archive.session_dir is not None
    assert len(list(archive.session_dir.glob("tool-*.json"))) == 1
    assert len(list(archive.session_dir.glob("history-*.json"))) == 1
    asyncio.run(conversation.close())
