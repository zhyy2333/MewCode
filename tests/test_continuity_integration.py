from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mewcode.agent import AgentRunner, StopReason, ToolScheduler
from mewcode.continuity import (
    ContinuityPaths,
    InstructionLoader,
    MemoryAction,
    MemoryCategory,
    MemoryManager,
    MemoryMutation,
    MemoryScope,
    MemoryStore,
    MemoryUpdatePlan,
    SessionOpenMode,
    SessionOpenRequest,
    SessionRepository,
)
from mewcode.conversation import Conversation
from mewcode.providers import ChatMessage, MessageKind, ProviderTextDelta, ProviderToolCall
from mewcode.tools import ToolRegistry

from tests.fakes import (
    AllowAllPermissionController,
    ControlledTool,
    ScriptedAsyncProvider,
    collect_async,
    tool_call,
)

DAY_ONE = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
DAY_TWO = DAY_ONE + timedelta(days=1, minutes=1)


class FixedUpdater:
    def __init__(self, plan: MemoryUpdatePlan) -> None:
        self.plan = plan
        self.calls = 0

    async def update(self, turn, catalog):
        self.calls += 1
        return self.plan


class OpenAIScriptedProvider(ScriptedAsyncProvider):
    def assistant_messages(self, response, group_id=None):
        messages = []
        if response.text or not response.tool_calls:
            messages.append(
                ChatMessage("assistant", response.text, MessageKind.ASSISTANT, group_id)
            )
        messages.extend(
            ChatMessage(
                "assistant",
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": call.raw_arguments,
                },
                MessageKind.TOOL_CALL,
                group_id,
            )
            for call in response.tool_calls
        )
        return messages

    def tool_result_messages(self, executions, group_id=None):
        return [
            ChatMessage(
                "tool",
                {
                    "type": "function_call_output",
                    "call_id": execution.request.id,
                    "output": execution.result.content,
                },
                MessageKind.TOOL_RESULT,
                group_id,
            )
            for execution in executions
        ]


def _plan() -> MemoryUpdatePlan:
    return MemoryUpdatePlan(
        1,
        (
            MemoryMutation(
                MemoryAction.UPSERT,
                MemoryScope.PROJECT,
                category=MemoryCategory.PROJECT_KNOWLEDGE,
                summary="project uses Python 3.11",
                body="The project targets Python 3.11.",
                priority=1,
            ),
            MemoryMutation(
                MemoryAction.UPSERT,
                MemoryScope.USER,
                category=MemoryCategory.USER_PREFERENCE,
                summary="user prefers concise replies",
                body="Keep replies concise.",
                priority=1,
            ),
        ),
    )


def test_end_to_end_restart_restores_history_instructions_gap_and_memory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    user_root = tmp_path / "user"
    paths = ContinuityPaths.for_workspace(workspace, user_root=user_root)
    paths.project_local_instructions.parent.mkdir(parents=True)
    paths.project_local_instructions.write_text("local first", encoding="utf-8")
    paths.project_root_instructions.write_text("root second", encoding="utf-8")
    paths.user_instructions.parent.mkdir(parents=True)
    paths.user_instructions.write_text("user third", encoding="utf-8")
    instructions = InstructionLoader().load(paths)
    ids = iter(("mem-project1", "mem-user001"))
    store = MemoryStore(paths, id_factory=lambda: next(ids))
    updater = FixedUpdater(_plan())
    memory = MemoryManager(store, updater)
    first_repo = SessionRepository(
        paths, clock=lambda: DAY_ONE, suffix_factory=lambda: "abcd"
    )
    opened = first_repo.open(SessionOpenRequest(SessionOpenMode.NEW))
    session_id = opened.state.session_id
    first_provider = OpenAIScriptedProvider(
        [
            [ProviderToolCall(tool_call("call-1", "echo"))],
            [ProviderTextDelta("finished")],
        ]
    )
    first = Conversation(
        AgentRunner(
            first_provider,
            ToolScheduler(AllowAllPermissionController()),
            id_factory=lambda: "run-1",
        ),
        ToolRegistry([ControlledTool("echo")]),
        initial_state=opened.state,
        session=opened.binding,
        instructions=instructions,
        memory=memory,
    )
    events = asyncio.run(collect_async(first.ask("do the work")))
    assert events[-1].reason is StopReason.COMPLETED
    asyncio.run(first.close())
    assert updater.calls == 1

    second_repo = SessionRepository(
        paths, clock=lambda: DAY_TWO, suffix_factory=lambda: "ef01"
    )
    resumed = second_repo.open(SessionOpenRequest())
    second_memory = MemoryManager(store, FixedUpdater(MemoryUpdatePlan(1, ())))
    second_provider = OpenAIScriptedProvider([[ProviderTextDelta("welcome back")]])
    second = Conversation(
        AgentRunner(
            second_provider,
            ToolScheduler(AllowAllPermissionController()),
            id_factory=lambda: "run-2",
        ),
        ToolRegistry([]),
        initial_state=resumed.state,
        session=resumed.binding,
        instructions=InstructionLoader().load(paths),
        memory=second_memory,
    )
    resumed_events = asyncio.run(collect_async(second.ask("continue")))

    assert resumed.resumed is True and resumed.state.session_id == session_id
    assert any(message.kind is MessageKind.RESUME_NOTICE for message in resumed.state.messages)
    assert resumed_events[-1].reason is StopReason.COMPLETED
    request = second_provider.calls[0]
    assert len(request.messages) >= 5
    dynamic = request.prompt.dynamic_system
    assert dynamic.index("local first") < dynamic.index("root second") < dynamic.index("user third")
    assert dynamic.index("project uses Python 3.11") < dynamic.index("user prefers concise replies")
    assert "instructions take precedence" in dynamic
    asyncio.run(second.close())
