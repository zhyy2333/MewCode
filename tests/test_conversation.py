from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mewcode.agent import AgentContextStatus, AgentRunner, StopReason, ToolScheduler
from mewcode.continuity import InstructionSnapshot, MemoryPromptView, SessionState
from mewcode.context import ContextArchive, ContextConfig, ContextManager
from mewcode.conversation import Conversation, ConversationError, ConversationMode
from mewcode.providers import ChatMessage, ModelRequest, ModelResponse, ProviderError, ProviderEvent, ProviderTextDelta, RequestBoundaryProvider, TokenUsage
from mewcode.prompting import PromptAdditions
from mewcode.tools import ToolExecution, ToolRegistry, ToolResult
from mewcode.subagents import (
    SubagentNotification,
    SubagentNotificationQueue,
    SubagentTaskManager,
    SubagentTaskStatus,
    TaskCancelResult,
)
from mewcode.hooks.models import (
    CommandHookAction,
    HookActionOutcome,
    HookCatalog,
    HookEvent,
    HookOutcomeKind,
    HookRule,
    HookRuleKey,
    HookSource,
    PromptHookAction,
)
from mewcode.hooks.provider import HookedProvider
from mewcode.hooks.runtime import HookRuntime
from types import MappingProxyType
import json

from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider, collect_async
from datetime import datetime, timezone


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


def test_session_turn_and_message_lifecycles_are_paired(tmp_path: Path) -> None:
    class RecordingExecutor:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def execute(self, rule, envelope, *, expects_decision):
            self.events.append(json.loads(envelope.encoded)["event"])
            return HookActionOutcome(HookOutcomeKind.SUCCESS)

        async def close(self):
            return None

    event_names = (
        HookEvent.SESSION_START,
        HookEvent.SESSION_END,
        HookEvent.TURN_START,
        HookEvent.TURN_END,
        HookEvent.MESSAGE_BEFORE,
        HookEvent.MESSAGE_AFTER,
    )
    rules = tuple(
        HookRule(
            HookRuleKey(HookSource.USER, Path("h"), index),
            event,
            None,
            CommandHookAction("ignored"),
        )
        for index, event in enumerate(event_names)
    )
    executor = RecordingExecutor()
    runtime = HookRuntime(
        HookCatalog(
            rules,
            MappingProxyType(
                {event: tuple(rule for rule in rules if rule.event is event) for event in event_names}
            ),
        ),
        executor,
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )
    base = ScriptedAsyncProvider([[ProviderTextDelta("hello")]])
    provider = HookedProvider(base, runtime, "main")
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController(), hook_runtime=runtime),
        id_factory=lambda: "run",
        hook_runtime=runtime,
    )
    conversation = Conversation(runner, ToolRegistry([]), hook_runtime=runtime)

    async def scenario() -> None:
        await conversation.start()
        await collect_async(conversation.ask("Hi"))
        await conversation.close()

    asyncio.run(scenario())
    assert executor.events == [
        "session.start",
        "turn.start",
        "message.before",
        "message.after",
        "turn.end",
        "session.end",
    ]


def test_reset_clears_messages_and_pending_plan_in_memory() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("hello")]])
    conversation = make_conversation(provider)
    asyncio.run(collect_async(conversation.ask("Hi")))
    assert conversation.messages()
    asyncio.run(conversation.reset())
    assert conversation.messages() == []
    assert conversation.pending_plan() is None


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


def test_compact_before_prompt_reaches_summary_and_after_is_paired(tmp_path: Path) -> None:
    class Executor:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def execute(self, rule, envelope, *, expects_decision):
            self.events.append(json.loads(envelope.encoded)["event"])
            return HookActionOutcome(HookOutcomeKind.SUCCESS)

        async def close(self):
            return None

    before = HookRule(
        HookRuleKey(HookSource.USER, Path("h"), 0),
        HookEvent.COMPACT_BEFORE,
        None,
        PromptHookAction("summary-only-context"),
    )
    after = HookRule(
        HookRuleKey(HookSource.USER, Path("h"), 1),
        HookEvent.COMPACT_AFTER,
        None,
        CommandHookAction("ignored"),
    )
    executor = Executor()
    runtime = HookRuntime(
        HookCatalog(
            (before, after),
            MappingProxyType(
                {HookEvent.COMPACT_BEFORE: (before,), HookEvent.COMPACT_AFTER: (after,)}
            ),
        ),
        executor,
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )
    base = ScriptedAsyncProvider(
        [
            *[[ProviderTextDelta(f"answer-{index}")] for index in range(5)],
            [ProviderTextDelta(summary_response(".mewcode/context/session/history-000001.json"))],
        ]
    )
    provider = HookedProvider(base, runtime, "main")
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
    archive.start()
    manager = ContextManager(
        provider,
        archive,
        ContextConfig(128_000, recent_tokens=1, recent_messages=2),
        hook_runtime=runtime,
    )
    conversation = Conversation(
        AgentRunner(
            provider,
            ToolScheduler(AllowAllPermissionController(), hook_runtime=runtime),
            context_manager=manager,
            hook_runtime=runtime,
        ),
        ToolRegistry([]),
        context_manager=manager,
        hook_runtime=runtime,
    )
    for index in range(5):
        asyncio.run(collect_async(conversation.ask(f"question-{index}")))
    asyncio.run(collect_async(conversation.compact()))
    assert "summary-only-context" in base.calls[-1].prompt.dynamic_system
    assert all(
        "summary-only-context" not in call.prompt.dynamic_system
        for call in base.calls[:-1]
    )
    assert executor.events == ["system.compact.after"]
    asyncio.run(conversation.close())


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


class FakeTaskManager:
    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.notifications = SubagentNotificationQueue()
        self.snapshots = ()
        self.cancel_result = TaskCancelResult.NOT_FOUND
        self.detached = None
        self.reset_error = None

    def list(self):
        return self.snapshots

    def get(self, task_id):
        return next((item for item in self.snapshots if item.task_id == task_id), None)

    async def cancel(self, task_id):
        self.log.append(f"cancel:{task_id}")
        return self.cancel_result

    async def detach_current_foreground(self, reason):
        self.log.append(f"detach:{reason}")
        return self.detached

    async def terminal_events(self):
        if False:
            yield None

    async def reset(self):
        self.log.append("tasks.reset")
        if self.reset_error:
            raise self.reset_error
        self.notifications.clear()
        return ()

    async def close(self):
        self.log.append("tasks.close")
        return ()


def test_conversation_task_facade_forwards_and_has_safe_unavailable_defaults() -> None:
    async def scenario():
        plain = make_conversation(ScriptedAsyncProvider([]))
        assert plain.has_subagent_tasks() is False
        assert plain.list_subagent_tasks() == ()
        assert plain.get_subagent_task("x") is None
        assert await plain.cancel_subagent_task("x") is TaskCancelResult.NOT_FOUND
        assert await plain.background_foreground_subagent() is None
        assert await collect_async(plain.subagent_terminal_events()) == []

        manager = FakeTaskManager()
        manager.cancel_result = TaskCancelResult.REQUESTED
        manager.detached = "task-1"
        runner = AgentRunner(
            ScriptedAsyncProvider([]),
            ToolScheduler(AllowAllPermissionController()),
        )
        conversation = Conversation(runner, ToolRegistry([]), task_manager=manager)
        assert conversation.has_subagent_tasks() is True
        assert await conversation.cancel_subagent_task("task-1") is TaskCancelResult.REQUESTED
        assert await conversation.background_foreground_subagent() == "task-1"
        assert manager.log == ["cancel:task-1", "detach:manual"]

    asyncio.run(scenario())


def test_root_request_consumes_notification_without_committing_it_to_history() -> None:
    queue = SubagentNotificationQueue()
    queue.enqueue_once(
        SubagentNotification(
            "task-1",
            SubagentTaskStatus.COMPLETED,
            "reviewer",
            "background result",
            None,
            False,
            TokenUsage(1, 1, 2),
            datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
    )
    manager = FakeTaskManager()
    manager.notifications = queue
    inner = ScriptedAsyncProvider([[ProviderTextDelta("answer")]])
    runner = AgentRunner(
        RequestBoundaryProvider(inner),
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    conversation = Conversation(runner, ToolRegistry([]), task_manager=manager)

    asyncio.run(collect_async(conversation.ask("question")))

    assert "## Completed Subagent Tasks" in inner.calls[0].prompt.dynamic_system
    assert "background result" in inner.calls[0].prompt.dynamic_system
    assert queue.pending_count == 0
    assert all("background result" not in str(message.content) for message in conversation.messages())


def test_notification_completed_during_run_enters_next_iteration() -> None:
    queue = SubagentNotificationQueue()
    manager = FakeTaskManager()
    manager.notifications = queue

    class EnqueueTool:
        name = "enqueue"
        description = "enqueue completion"
        parameters_schema = {"type": "object", "properties": {}}
        from mewcode.tools import ToolSafety, ToolPermissionSpec, PermissionTargetKind
        safety = ToolSafety.READ_ONLY
        permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL, "enqueue")

        async def execute(self, arguments):
            queue.enqueue_once(
                SubagentNotification(
                    "task-2",
                    SubagentTaskStatus.COMPLETED,
                    None,
                    "during run",
                    None,
                    False,
                    TokenUsage.zero(),
                    datetime.now(timezone.utc),
                )
            )
            return ToolResult(True, "enqueue", "ok")

    from tests.fakes import tool_call
    from mewcode.providers import ProviderToolCall

    inner = ScriptedAsyncProvider(
        [[ProviderToolCall(tool_call("1", "enqueue"))], [ProviderTextDelta("done")]]
    )
    registry = ToolRegistry([EnqueueTool()])
    runner = AgentRunner(
        RequestBoundaryProvider(inner),
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
    )
    conversation = Conversation(runner, registry, task_manager=manager)
    asyncio.run(collect_async(conversation.ask("question")))

    assert "Completed Subagent Tasks" not in inner.calls[0].prompt.dynamic_system
    assert "during run" in inner.calls[1].prompt.dynamic_system
    assert all("during run" not in str(message.content) for message in conversation.messages())


def test_reset_calls_task_manager_first_and_stops_on_task_failure() -> None:
    async def scenario(fail):
        log = []
        manager = FakeTaskManager(log)
        if fail:
            manager.reset_error = RuntimeError("bad")

        class Memory:
            def prompt_view(self): return MemoryPromptView()
            async def await_pending(self): log.append("memory.await"); return ()
            async def close(self): return ()

        runner = AgentRunner(
            ScriptedAsyncProvider([]),
            ToolScheduler(AllowAllPermissionController()),
        )
        conversation = Conversation(
            runner,
            ToolRegistry([]),
            memory=Memory(),
            task_manager=manager,
        )
        if fail:
            with pytest.raises(ConversationError, match="Subagent tasks"):
                await conversation.reset()
        else:
            await conversation.reset()
        return log

    assert asyncio.run(scenario(False))[:2] == ["tasks.reset", "memory.await"]
    assert asyncio.run(scenario(True)) == ["tasks.reset"]


def test_close_stops_task_manager_before_memory() -> None:
    async def scenario():
        log = []
        manager = FakeTaskManager(log)

        class Memory:
            def prompt_view(self): return MemoryPromptView()
            async def await_pending(self): return ()
            async def close(self): log.append("memory.close"); return ()

        runner = AgentRunner(
            ScriptedAsyncProvider([]),
            ToolScheduler(AllowAllPermissionController()),
        )
        conversation = Conversation(
            runner,
            ToolRegistry([]),
            memory=Memory(),
            task_manager=manager,
        )
        await conversation.close()
        await conversation.close()
        return log

    assert asyncio.run(scenario()) == ["tasks.close", "memory.close"]


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
