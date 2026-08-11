from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mewcode.agent import AgentContextStatus, AgentRunner, StopReason, ToolScheduler
from mewcode.continuity import InstructionSnapshot, MemoryPromptView, SessionState
from mewcode.context import ContextArchive, ContextConfig, ContextManager
from mewcode.conversation import Conversation, ConversationError, ConversationMode
from mewcode.providers import ChatMessage, ModelRequest, ModelResponse, ProviderError, ProviderEvent, ProviderTextDelta
from mewcode.prompting import PromptAdditions
from mewcode.tools import ToolExecution, ToolRegistry

from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider, collect_async


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
        "<analysis_draft>draft</analysis_draft>"
        f"<formal_summary>{body}</formal_summary>"
    )


def make_conversation(provider, tools: ToolRegistry | None = None) -> Conversation:
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    return Conversation(runner, tools or ToolRegistry([]))


def test_ask_streams_parts_and_appends_history() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("hel"), ProviderTextDelta("lo")]])
    conversation = make_conversation(provider)

    events = asyncio.run(collect_async(conversation.ask("Hi")))

    assert events[-1].reason is StopReason.COMPLETED
    assert conversation.messages()[0] == ChatMessage("user", "Hi")
    assert conversation.messages()[-1].content["text"] == "hello"


def test_messages_returns_copy() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("hello")]])
    conversation = make_conversation(provider)
    asyncio.run(collect_async(conversation.ask("Hi")))

    copied = conversation.messages()
    copied.clear()
    assert len(conversation.messages()) == 2


def test_conversation_status_is_safe_dynamic_and_marks_resumed() -> None:
    provider = ScriptedAsyncProvider([])
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    conversation = Conversation(
        runner,
        ToolRegistry([]),
        initial_state=SessionState(
            "session-id", (ChatMessage("user", "token secret=longvalue hello"),)
        ),
        resumed=True,
    )
    status = conversation.status()
    assert status.session_id == "session-id"
    assert status.resumed is True
    assert status.message_count == 1
    assert status.busy is False
    assert "secret=longvalue" not in status.title


def test_manual_compact_force_replaces_history_without_adding_command(tmp_path: Path) -> None:
    path = ".mewcode/context/session/history-000001.json"
    provider = ScriptedAsyncProvider(
        [
            *[[ProviderTextDelta(f"answer-{index}")] for index in range(5)],
            [ProviderTextDelta(summary_response(path))],
        ]
    )
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
    archive.start()
    manager = ContextManager(
        provider,
        archive,
        ContextConfig(128_000, recent_tokens=1, recent_messages=2),
    )
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
        context_manager=manager,
    )
    conversation = Conversation(
        runner,
        ToolRegistry([]),
        context_manager=manager,
    )
    for index in range(5):
        asyncio.run(collect_async(conversation.ask(f"question-{index}")))

    events = asyncio.run(collect_async(conversation.compact()))
    messages = conversation.messages()

    assert any(isinstance(event, AgentContextStatus) for event in events)
    assert messages[0].kind.value == "summary"
    assert messages[1].kind.value == "boundary"
    assert all(message.content != "/compact" for message in messages)
    assert len(provider.calls) == 6
    session_dir = archive.session_dir
    assert asyncio.run(conversation.close()) == ()
    assert session_dir is not None and not session_dir.exists()


def test_stable_prefix_second_turn_includes_previous_context() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("first")], [ProviderTextDelta("second")]]
    )
    conversation = make_conversation(provider)
    asyncio.run(collect_async(conversation.ask("one")))
    asyncio.run(collect_async(conversation.ask("two")))

    assert len(provider.calls[1].messages) == 3
    assert provider.calls[1].messages[0] == ChatMessage("user", "one")
    assert (
        provider.calls[0].prompt.stable_system
        == provider.calls[1].prompt.stable_system
    )


def test_provider_error_does_not_append_partial_history() -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("partial"), ProviderError("failed")]]
    )
    conversation = make_conversation(provider)
    events = asyncio.run(collect_async(conversation.ask("Hi")))

    assert events[-1].reason is StopReason.STREAM_ERROR
    assert conversation.messages() == []


class BlockingProvider(ScriptedAsyncProvider):
    def __init__(self, started: asyncio.Event) -> None:
        super().__init__([])
        self.started = started

    async def stream_reply(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ProviderEvent]:
        self.calls.append(request)
        self.started.set()
        await asyncio.Event().wait()
        if False:
            yield ProviderTextDelta("")


def test_active_run_is_guarded_and_cancelled() -> None:
    async def scenario() -> Conversation:
        started = asyncio.Event()
        conversation = make_conversation(BlockingProvider(started))
        active = asyncio.create_task(collect_async(conversation.ask("one")))
        await started.wait()
        with pytest.raises(ConversationError, match="already active"):
            await collect_async(conversation.ask("two"))
        await conversation.cancel_active()
        events = await active
        assert events[-1].reason is StopReason.CANCELLED
        return conversation

    conversation = asyncio.run(scenario())
    assert conversation.messages() == []


def test_empty_direct_message_is_rejected() -> None:
    conversation = make_conversation(ScriptedAsyncProvider([]))
    with pytest.raises(ConversationError, match="empty"):
        asyncio.run(collect_async(conversation.ask("  ")))


def test_prompt_additions_are_system_context_with_real_user_history() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    conversation = Conversation(
        runner,
        ToolRegistry([]),
        PromptAdditions("custom", "skill", "memory"),
    )
    asyncio.run(collect_async(conversation.ask("real question")))

    dynamic = provider.calls[0].prompt.dynamic_system
    assert dynamic.index("custom") < dynamic.index("skill") < dynamic.index("memory")
    assert [message.content for message in conversation.messages() if message.role == "user"] == [
        "real question"
    ]


class BlockingMemoryManager:
    def __init__(self, release: asyncio.Event) -> None:
        self.release = release
        self.pending = None
        self.view = MemoryPromptView()
        self.scheduled = 0

    def prompt_view(self):
        return self.view

    def schedule(self, turn):
        self.scheduled += 1
        self.pending = asyncio.create_task(self._update())

    async def _update(self):
        await self.release.wait()
        self.view = MemoryPromptView("new memory", 1, 10, ("mem-abcdef",))

    async def await_pending(self):
        if self.pending is not None:
            await self.pending
            self.pending = None
        return ()

    async def close(self):
        return await self.await_pending()


def test_next_turn_waits_for_memory_and_uses_refreshed_prompt() -> None:
    async def scenario():
        release = asyncio.Event()
        provider = ScriptedAsyncProvider(
            [[ProviderTextDelta("first")], [ProviderTextDelta("second")]]
        )
        memory = BlockingMemoryManager(release)
        runner = AgentRunner(
            provider,
            ToolScheduler(AllowAllPermissionController()),
            id_factory=lambda: "run",
        )
        conversation = Conversation(runner, ToolRegistry([]), memory=memory)
        first = await collect_async(conversation.ask("one"))
        assert first[-1].reason is StopReason.COMPLETED
        assert memory.scheduled == 1
        second_task = asyncio.create_task(collect_async(conversation.ask("two")))
        await asyncio.sleep(0)
        assert len(provider.calls) == 1
        release.set()
        second = await second_task
        await conversation.close()
        return provider, second

    provider, second = asyncio.run(scenario())
    assert second[-1].reason is StopReason.COMPLETED
    assert "new memory" in provider.calls[1].prompt.dynamic_system


def test_instructions_precede_custom_and_memory_is_reference_section() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("done")]])
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    conversation = Conversation(
        runner,
        ToolRegistry([]),
        PromptAdditions(custom_instructions="base custom", long_term_memory="base memory"),
        instructions=InstructionSnapshot("project instruction"),
    )
    asyncio.run(collect_async(conversation.ask("question")))
    dynamic = provider.calls[0].prompt.dynamic_system
    assert dynamic.index("project instruction") < dynamic.index("base custom")
    assert dynamic.index("base custom") < dynamic.index("base memory")


def test_non_completed_run_does_not_schedule_memory() -> None:
    release = asyncio.Event()
    memory = BlockingMemoryManager(release)
    conversation = make_conversation(
        ScriptedAsyncProvider([[ProviderError("failed")]])
    )
    conversation._memory = memory
    events = asyncio.run(collect_async(conversation.ask("question")))
    assert events[-1].reason is StopReason.STREAM_ERROR
    assert memory.scheduled == 0
