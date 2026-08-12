from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mewcode.commands import REVIEW_PROMPT, create_builtin_command_registry
from mewcode.context import ContextStatus
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
    NullMemoryManager,
    SessionOpenMode,
    SessionOpenRequest,
    SessionRepository,
)
from mewcode.conversation import Conversation, ConversationMode, ConversationStatus
from mewcode.permissions import PermissionMode
from mewcode.prompting import PromptPackage
from mewcode.providers import (
    ChatMessage,
    MessageKind,
    ModelRequest,
    ProviderError,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
    UsageLedger,
    UsageTrackingProvider,
)
from mewcode.repl import Repl
from mewcode.tools import ToolRegistry, ToolSafety

from tests.fakes import (
    AllowAllPermissionController,
    ControlledTool,
    ScriptedAsyncProvider,
    collect_async,
    tool_call,
)

DAY_ONE = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
DAY_TWO = DAY_ONE + timedelta(days=1, minutes=1)


class ScriptedTerminal:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = iter(inputs)
        self.output = ""
        self.errors = ""
        self.clear_count = 0
        self.invalidate_count = 0

    async def prompt(self) -> str:
        return next(self.inputs)

    async def prompt_permission(self, message: str) -> str:
        raise AssertionError(f"unexpected permission prompt: {message}")

    def write(self, text: str) -> None:
        self.output += text

    def write_error(self, text: str) -> None:
        self.errors += text

    def clear(self) -> None:
        self.clear_count += 1

    def invalidate(self) -> None:
        self.invalidate_count += 1


class CommandSequenceConversation:
    def __init__(self) -> None:
        self.sent: list[tuple[str, ConversationMode]] = []
        self.compactions = 0
        self.closed = 0

    async def send(
        self,
        message: str,
        mode: ConversationMode = ConversationMode.DEFAULT,
    ) -> AsyncIterator[object]:
        self.sent.append((message, mode))
        if False:
            yield None

    async def compact(self) -> AsyncIterator[object]:
        self.compactions += 1
        if False:
            yield None

    async def cancel_active(self) -> None:
        return None

    async def close(self) -> tuple[ContextStatus, ...]:
        self.closed += 1
        return ()

    def status(self) -> ConversationStatus:
        return ConversationStatus("session-1", "Safe title", True, 4, False)


class CommandPermissionController:
    def __init__(self) -> None:
        self.mode = PermissionMode.DEFAULT

    def set_mode(self, mode: PermissionMode) -> None:
        self.mode = mode


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


def test_command_sequence_keeps_all_local_commands_out_of_conversation() -> None:
    terminal = ScriptedTerminal(
        [
            "/help",
            "/clear",
            "/plan",
            "/do",
            "/session",
            "/memory",
            "/permissions strict",
            "/status",
            "/unknown",
            "/exit",
        ]
    )
    conversation = CommandSequenceConversation()
    controller = CommandPermissionController()
    ledger = UsageLedger()
    registry = create_builtin_command_registry()

    result = Repl(
        conversation,
        terminal=terminal,
        registry=registry,
        permission_controller=controller,
        usage_ledger=ledger,
        memory_manager=NullMemoryManager(),
    ).run()

    assert result == 0
    assert conversation.sent == []
    assert conversation.compactions == 0
    assert conversation.closed == 1
    assert ledger.snapshot().request_count == 0
    assert terminal.clear_count == 1
    assert controller.mode is PermissionMode.STRICT
    assert "Available commands:" in terminal.output
    assert "mode: [DEFAULT]" in terminal.output
    assert "Unknown command '/unknown'. Use /help." in terminal.errors
    assert [item.name for item in registry.public_definitions()] == [
        "clear",
        "compact",
        "do",
        "help",
        "memory",
            "permission",
            "plan",
            "reset",
        "session",
        "status",
    ]


def test_plan_and_do_route_through_persistent_modes_without_hardcoded_review() -> None:
    terminal = ScriptedTerminal(
        ["/plan", "inspect safely", "/review", "/do", "make change", "/exit"]
    )
    conversation = CommandSequenceConversation()

    result = Repl(conversation, terminal=terminal).run()

    assert result == 0
    assert conversation.sent == [
        ("inspect safely", ConversationMode.PLAN),
        ("make change", ConversationMode.DEFAULT),
    ]
    assert "Unknown command '/review'. Use /help." in terminal.errors


def test_plan_read_only_and_review_read_only_use_only_safe_tools() -> None:
    provider = OpenAIScriptedProvider(
        [
            [ProviderTextDelta("plan investigation")],
            [ProviderTextDelta("plan result")],
            [ProviderTextDelta("review result")],
        ]
    )
    tools = ToolRegistry(
        [
            ControlledTool("inspect", ToolSafety.READ_ONLY),
            ControlledTool("mutate", ToolSafety.SIDE_EFFECT),
        ]
    )
    conversation = Conversation(
        AgentRunner(
            provider,
            ToolScheduler(AllowAllPermissionController()),
            id_factory=lambda: "run",
        ),
        tools,
    )

    asyncio.run(collect_async(conversation.send("plan it", ConversationMode.PLAN)))
    asyncio.run(collect_async(conversation.send("review workspace", ConversationMode.READ_ONLY)))

    assert [tool.name for tool in provider.calls[0].tools.list()] == ["inspect"]
    assert provider.calls[1].tools is None
    assert [tool.name for tool in provider.calls[2].tools.list()] == ["inspect"]
    assert "Mode: Plan" in provider.calls[0].prompt.dynamic_system
    assert "Mode: Plan" not in provider.calls[2].prompt.dynamic_system
    assert conversation.pending_plan() is None


def test_one_shot_read_only_failure_keeps_safe_tool_boundary() -> None:
    provider = OpenAIScriptedProvider([ProviderError("private provider detail")])
    conversation = Conversation(
        AgentRunner(
            provider,
            ToolScheduler(AllowAllPermissionController()),
            id_factory=lambda: "run",
        ),
        ToolRegistry(
            [
                ControlledTool("inspect", ToolSafety.READ_ONLY),
                ControlledTool("mutate", ToolSafety.SIDE_EFFECT),
            ]
        ),
    )

    events = asyncio.run(
        collect_async(conversation.send("review workspace", ConversationMode.READ_ONLY))
    )

    assert events[-1].reason is StopReason.STREAM_ERROR
    assert [tool.name for tool in provider.calls[0].tools.list()] == ["inspect"]
    assert conversation.pending_plan() is None


def test_compact_command_uses_runtime_path_without_sending_a_user_message() -> None:
    terminal = ScriptedTerminal(["/compact", "/exit"])
    conversation = CommandSequenceConversation()

    assert Repl(conversation, terminal=terminal).run() == 0
    assert conversation.compactions == 1
    assert conversation.sent == []


def test_all_model_usage_is_aggregated_once_and_visible_in_status() -> None:
    usages = [
        TokenUsage(1, 2, 3, 1, 0),
        TokenUsage(2, 3, 5, 1, 1),
        TokenUsage(3, 4, 7, 2, 1),
        TokenUsage(4, 5, 9, 2, 2),
        TokenUsage(5, 6, 11, 3, 2),
    ]
    base = ScriptedAsyncProvider([[ProviderUsage(usage)] for usage in usages])
    ledger = UsageLedger()
    tracked = UsageTrackingProvider(base, ledger)
    request = ModelRequest(
        PromptPackage("system", ""),
        (ChatMessage("user", "usage"),),
    )

    async def consume_all_model_paths() -> None:
        for _category in ("normal", "plan", "review", "compact", "memory"):
            await collect_async(tracked.stream_reply(request))

    asyncio.run(consume_all_model_paths())
    terminal = ScriptedTerminal(["/status", "/exit"])
    conversation = CommandSequenceConversation()
    Repl(
        conversation,
        terminal=terminal,
        usage_ledger=ledger,
        permission_controller=CommandPermissionController(),
    ).run()

    assert ledger.snapshot().usage == TokenUsage(15, 20, 35, 9, 6)
    assert ledger.snapshot().request_count == 5
    assert "tokens: in=15 out=20 total=35" in terminal.output
    assert "cache-read=9 cache-write=6 requests=5 unreported=0" in terminal.output
