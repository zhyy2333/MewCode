from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import pytest

from mewcode.continuity import (
    MemoryAction,
    MemoryCategory,
    MemoryConfig,
    MemoryError,
    MemoryIndexEntry,
    MemoryScope,
    MemoryTurn,
    MemoryUpdater,
)
from mewcode.continuity.memory_updater import parse_memory_update
from mewcode.providers import (
    ProviderFinished,
    ProviderFinishReason,
    ProviderTextDelta,
    ProviderToolCall,
)
from tests.fakes import ScriptedAsyncProvider, tool_call

NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def _response(mutations) -> str:
    return "<memory_update>" + json.dumps(
        {"version": 1, "mutations": mutations}
    ) + "</memory_update>"


def test_request_is_tool_free_bounded_and_marks_data_as_untrusted() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta(_response([]))]])
    updater = MemoryUpdater(provider)
    turn = MemoryTurn("session", "remember concise replies", "Okay", NOW)
    plan = asyncio.run(updater.update(turn, ()))

    assert plan.mutations == ()
    request = provider.calls[0]
    assert request.tools is None
    assert request.max_output_tokens == 4096
    assert "never as instructions" in request.prompt.stable_system
    assert "remember concise replies" in request.messages[0].content


def test_parser_accepts_new_update_delete_and_rejects_extra_text() -> None:
    plan = parse_memory_update(
        _response(
            [
                {
                    "action": "upsert",
                    "scope": "project",
                    "note_id": None,
                    "category": "project_knowledge",
                    "summary": "Python 3.11",
                    "body": "Use Python 3.11.",
                    "priority": 1,
                },
                {"action": "delete", "scope": "user", "note_id": "mem-abcdef"},
            ]
        )
    )
    assert plan.mutations[0].action is MemoryAction.UPSERT
    assert plan.mutations[0].category is MemoryCategory.PROJECT_KNOWLEDGE
    assert plan.mutations[1].action is MemoryAction.DELETE
    with pytest.raises(MemoryError):
        parse_memory_update("comment\n" + _response([]))


@pytest.mark.parametrize(
    "script",
    [
        [ProviderToolCall(tool_call("1", "echo"))],
        [ProviderTextDelta(_response([])), ProviderFinished(ProviderFinishReason.OUTPUT_LIMIT)],
        [ProviderTextDelta("not json")],
    ],
)
def test_collector_rejects_tools_truncation_and_malformed_output(script) -> None:
    updater = MemoryUpdater(ScriptedAsyncProvider([script]))
    with pytest.raises(MemoryError):
        asyncio.run(updater.update(MemoryTurn("session", "user", "answer", NOW), ()))


def test_capacity_failure_skips_provider() -> None:
    provider = ScriptedAsyncProvider([])
    updater = MemoryUpdater(
        provider,
        MemoryConfig(update_context_tokens=64, update_max_output_tokens=32),
    )
    with pytest.raises(MemoryError):
        asyncio.run(
            updater.update(MemoryTurn("session", "x" * 1000, "answer", NOW), ())
        )
    assert provider.calls == []


def test_catalog_is_supplied_without_paths_or_note_bodies() -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta(_response([]))]])
    entry = MemoryIndexEntry(
        "mem-abcdef",
        MemoryScope.USER,
        MemoryCategory.USER_PREFERENCE,
        "concise output",
        1,
        NOW,
        "notes/mem-abcdef.md",
    )
    asyncio.run(
        MemoryUpdater(provider).update(
            MemoryTurn("session", "question", "answer", NOW), (entry,)
        )
    )
    payload = provider.calls[0].messages[0].content
    assert "concise output" in payload
    assert "notes/" not in payload
