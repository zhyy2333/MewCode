from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from mewcode.agent import AgentRunner, StopReason, ToolScheduler
from mewcode.continuity import (
    ContinuityPaths,
    SessionOpenMode,
    SessionOpenRequest,
    SessionRepository,
)
from mewcode.context import ContextArchive, ContextConfig, ContextManager
from mewcode.conversation import Conversation
from mewcode.providers import ProviderTextDelta
from mewcode.tools import ToolRegistry

from tests.fakes import AllowAllPermissionController, ScriptedAsyncProvider, collect_async

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _repository(tmp_path: Path) -> SessionRepository:
    paths = ContinuityPaths.for_workspace(
        tmp_path / "project", user_root=tmp_path / "user"
    )
    return SessionRepository(paths, clock=lambda: NOW, suffix_factory=lambda: "abcd")


def _conversation(provider, opened, context_manager=None) -> Conversation:
    runner = AgentRunner(
        provider,
        ToolScheduler(AllowAllPermissionController()),
        id_factory=lambda: "run",
        context_manager=context_manager,
    )
    return Conversation(
        runner,
        ToolRegistry([]),
        context_manager=context_manager,
        initial_state=opened.state,
        session=opened.binding,
    )


def test_history_and_pending_plan_survive_restart(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW)
    session_id = opened.state.session_id
    first = _conversation(
        ScriptedAsyncProvider(
            [
                [ProviderTextDelta("answer")],
                [ProviderTextDelta("investigation")],
                [ProviderTextDelta("steps")],
            ]
        ),
        opened,
    )
    asyncio.run(collect_async(first.ask("question")))
    asyncio.run(collect_async(first.plan("build it")))
    asyncio.run(first.close())

    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW)
    second = _conversation(ScriptedAsyncProvider([[ProviderTextDelta("done")]]), resumed)

    assert len(second.messages()) == 5
    assert second.pending_plan() is not None
    assert second.pending_plan().task == "build it"
    events = asyncio.run(collect_async(second.execute_plan()))
    assert events[-1].reason is StopReason.COMPLETED
    asyncio.run(second.close())

    final = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW)
    assert final.state.pending_plan is None
    final.binding.close()


def test_manual_compaction_is_persisted_before_memory_changes(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    opened = repo.open(SessionOpenRequest(SessionOpenMode.NEW), NOW)
    session_id = opened.state.session_id
    provider = ScriptedAsyncProvider(
        [
            *[[ProviderTextDelta(f"answer-{index}")] for index in range(5)],
            [ProviderTextDelta(_summary_response(".mewcode/context/session/history.json"))],
        ]
    )
    archive = ContextArchive(tmp_path / "context", session_id_factory=lambda: "session")
    archive.start()
    manager = ContextManager(
        provider, archive, ContextConfig(128_000, recent_tokens=1, recent_messages=2)
    )
    conversation = _conversation(provider, opened, manager)
    for index in range(5):
        asyncio.run(collect_async(conversation.ask(f"question-{index}")))
    asyncio.run(collect_async(conversation.compact()))
    compacted = tuple(conversation.messages())
    asyncio.run(conversation.close())

    resumed = repo.open(SessionOpenRequest(SessionOpenMode.RESUME, session_id), NOW)
    assert resumed.state.messages == compacted
    resumed.binding.close()


def _summary_response(path: str) -> str:
    titles = (
        "current goal",
        "constraints",
        "decisions",
        "completed",
        "code state",
        "risks",
        "next actions",
        "archive index",
    )
    body = "\n\n".join(
        f"## {index}. {title}\n{path if index == 8 else 'none'}"
        for index, title in enumerate(titles, start=1)
    )
    return f"<analysis_draft>draft</analysis_draft><formal_summary>{body}</formal_summary>"
