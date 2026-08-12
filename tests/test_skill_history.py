from __future__ import annotations

from mewcode.providers import ChatMessage, MessageKind
from mewcode.skills import project_recent_turns


def test_projects_recent_complete_turns_without_splitting_tool_chain() -> None:
    messages = (
        ChatMessage("user", "first"),
        ChatMessage("assistant", {"call": "1"}, MessageKind.TOOL_CALL, "g1"),
        ChatMessage("tool", {"result": "1"}, MessageKind.TOOL_RESULT, "g1"),
        ChatMessage("assistant", "done first", MessageKind.ASSISTANT),
        ChatMessage("system", "summary", MessageKind.SUMMARY),
        ChatMessage("user", "second"),
        ChatMessage("assistant", "done second", MessageKind.ASSISTANT),
    )

    projected = project_recent_turns(messages, 1)

    assert projected == (
        ChatMessage("user", "second", MessageKind.USER),
        ChatMessage("assistant", "[assistant]\ndone second", MessageKind.ASSISTANT),
    )


def test_ignores_incomplete_tail_and_zero_history() -> None:
    messages = (
        ChatMessage("user", "complete"),
        ChatMessage("assistant", "done", MessageKind.ASSISTANT),
        ChatMessage("user", "unfinished"),
        ChatMessage("assistant", {"call": "x"}, MessageKind.TOOL_CALL, "g"),
    )
    assert project_recent_turns(messages, 0) == ()
    projected = project_recent_turns(messages, 2)
    assert [message.content for message in projected] == [
        "complete",
        "[assistant]\ndone",
    ]


def test_provider_specific_tool_content_becomes_neutral_text() -> None:
    messages = (
        ChatMessage("user", "use tool"),
        ChatMessage(
            "assistant",
            [{"type": "tool_use", "id": "1", "name": "read", "input": {}}],
            MessageKind.TOOL_CALL,
            "g",
        ),
        ChatMessage(
            "user",
            [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}],
            MessageKind.TOOL_RESULT,
            "g",
        ),
        ChatMessage("assistant", "finished", MessageKind.ASSISTANT),
    )
    projected = project_recent_turns(messages, 1)
    assert "tool_use" in projected[1].content
    assert "tool_result" in projected[1].content
    assert projected[1].kind is MessageKind.ASSISTANT
