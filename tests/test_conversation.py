from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from mewcode.agent import AgentRunner, StopReason, ToolScheduler
from mewcode.conversation import Conversation, ConversationError
from mewcode.providers import ChatMessage, ModelRequest, ModelResponse, ProviderError, ProviderEvent, ProviderTextDelta
from mewcode.prompting import PromptAdditions
from mewcode.tools import ToolExecution, ToolRegistry

from tests.fakes import ScriptedAsyncProvider, collect_async


def make_conversation(provider, tools: ToolRegistry | None = None) -> Conversation:
    runner = AgentRunner(provider, ToolScheduler(), id_factory=lambda: "run")
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
    runner = AgentRunner(provider, ToolScheduler(), id_factory=lambda: "run")
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
