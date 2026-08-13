from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.context import (
    ContextArchive,
    ContextConfig,
    ContextError,
    ContextManager,
    ContextStatusKind,
    TokenEstimator,
)
from mewcode.prompting import PromptPackage
from mewcode.providers import ChatMessage, ModelRequest, ProviderTextDelta, TokenUsage

from tests.fakes import ScriptedAsyncProvider, collect_async


def request(messages: tuple[ChatMessage, ...]) -> ModelRequest:
    return ModelRequest(
        PromptPackage("stable", "dynamic"),
        messages,
        max_output_tokens=4_096,
    )


def large_history() -> tuple[ChatMessage, ...]:
    return tuple(
        ChatMessage("user" if index % 2 == 0 else "assistant", "x" * 10_000)
        for index in range(10)
    )


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


def consume(operation):
    statuses = asyncio.run(collect_async(operation.statuses()))
    return statuses, operation.outcome


def started_manager(
    tmp_path: Path,
    provider: ScriptedAsyncProvider,
) -> tuple[ContextArchive, ContextManager]:
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
    archive.start()
    manager = ContextManager(provider, archive, ContextConfig(40_000))
    return archive, manager


def test_context_runtime_status_tracks_breaker(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([])
    archive, manager = started_manager(tmp_path, provider)
    assert manager.status().automatic_compaction_enabled is True
    assert manager.status().consecutive_failures == 0
    manager._breaker.record_failure()
    manager._breaker.record_failure()
    manager._breaker.record_failure()
    assert manager.status().automatic_compaction_enabled is False
    assert manager.status().consecutive_failures == 3
    manager._breaker.record_success()
    assert manager.status().automatic_compaction_enabled is True
    assert manager.status().consecutive_failures == 0
    archive.close()


def test_below_threshold_request_passes_without_summary_call(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([])
    archive, manager = started_manager(tmp_path, provider)
    model_request = request((ChatMessage("user", "hello"),))

    statuses, outcome = consume(manager.prepare(model_request))

    assert statuses == []
    assert outcome.request is model_request
    assert outcome.changed is False
    assert provider.calls == []
    manager.observe_usage(outcome.footprint, TokenUsage(context_input_tokens=90))
    archive.close()


def test_automatic_threshold_triggers_exactly_at_computed_boundary(
    tmp_path: Path,
) -> None:
    model_request = request((ChatMessage("user", "x" * 20_000),))
    estimate = TokenEstimator().estimate(model_request).input_tokens
    boundary_window = estimate + model_request.max_output_tokens + 13_000

    below_provider = ScriptedAsyncProvider([])
    below_archive = ContextArchive(tmp_path / "below", session_id_factory=lambda: "s")
    below_archive.start()
    below = ContextManager(
        below_provider,
        below_archive,
        ContextConfig(boundary_window + 1),
    )
    statuses, outcome = consume(below.prepare(model_request))
    assert statuses == []
    assert outcome.request is model_request
    below_archive.close()

    at_provider = ScriptedAsyncProvider([])
    at_archive = ContextArchive(tmp_path / "at", session_id_factory=lambda: "s")
    at_archive.start()
    at = ContextManager(
        at_provider,
        at_archive,
        ContextConfig(boundary_window),
    )
    statuses, outcome = consume(at.prepare(model_request))
    assert statuses[0].kind is ContextStatusKind.COMPACTION_STARTED
    assert outcome.request is None
    assert at_provider.calls == []
    at_archive.close()


def test_automatic_compaction_rebuilds_request_before_main_model(tmp_path: Path) -> None:
    path = ".mewcode/context/session/history-000001.json"
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta(summary_response(path))]]
    )
    archive, manager = started_manager(tmp_path, provider)

    statuses, outcome = consume(manager.prepare(request(large_history())))

    assert [status.kind for status in statuses] == [
        ContextStatusKind.COMPACTION_STARTED,
        ContextStatusKind.COMPACTION_COMPLETED,
    ]
    assert outcome.request is not None
    assert outcome.changed is True
    assert len(outcome.messages) == 7
    assert provider.calls[0].tools is None
    assert provider.calls[0].max_output_tokens == 8_192
    archive.close()


def test_automatic_success_still_over_limit_keeps_summary_but_stops_main_call(
    tmp_path: Path,
) -> None:
    path = ".mewcode/context/session/history-000001.json"
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta(summary_response(path))]]
    )
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
    archive.start()
    manager = ContextManager(
        provider,
        archive,
        ContextConfig(40_000, recent_tokens=24_000, recent_messages=5),
    )
    messages = tuple(
        ChatMessage("user" if index % 2 == 0 else "assistant", "x" * 8_000)
        for index in range(15)
    )

    statuses, outcome = consume(manager.prepare(request(messages)))

    assert len(provider.calls) == 1
    assert outcome.request is None
    assert outcome.changed is True
    assert outcome.messages[0].kind.value == "summary"
    assert statuses[-1].kind is ContextStatusKind.COMPACTION_FAILED
    archive.close()


def test_automatic_failure_three_times_opens_breaker_and_stops_without_retry(
    tmp_path: Path,
) -> None:
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta("invalid")]] for _ in range(3)
    )
    archive, manager = started_manager(tmp_path, provider)
    model_request = request(large_history())

    for expected_failures in range(1, 4):
        statuses, outcome = consume(manager.prepare(model_request))
        assert outcome.request is None
        assert outcome.messages == model_request.messages
        assert manager.consecutive_failures == expected_failures
        assert ContextStatusKind.COMPACTION_FAILED in {
            status.kind for status in statuses
        }

    statuses, outcome = consume(manager.prepare(model_request))

    assert manager.automatic_compaction_disabled is True
    assert len(provider.calls) == 3
    assert outcome.request is None
    assert "/compact" in (outcome.error or "")
    assert [status.kind for status in statuses] == [ContextStatusKind.CIRCUIT_OPEN]
    archive.close()


def test_manual_recovery_allows_safe_requests_and_recovers_breaker(tmp_path: Path) -> None:
    scripts = [[ProviderTextDelta("invalid")] for _ in range(3)]
    scripts.append(
        [
            ProviderTextDelta(
                summary_response(
                    ".mewcode/context/session/history-000004.json"
                )
            )
        ]
    )
    provider = ScriptedAsyncProvider(scripts)
    archive, manager = started_manager(tmp_path, provider)
    model_request = request(large_history())
    for _ in range(3):
        consume(manager.prepare(model_request))

    safe_statuses, safe = consume(
        manager.prepare(request((ChatMessage("user", "safe"),)))
    )
    manual_statuses, manual = consume(manager.compact(model_request.messages))

    assert safe_statuses == []
    assert safe.request is not None
    assert manual.changed is True
    assert ContextStatusKind.CIRCUIT_RECOVERED in {
        status.kind for status in manual_statuses
    }
    assert manager.consecutive_failures == 0
    assert manager.automatic_compaction_disabled is False
    archive.close()


def test_manual_no_compaction_needed_does_not_call_provider_or_change_history(
    tmp_path: Path,
) -> None:
    provider = ScriptedAsyncProvider([])
    archive, manager = started_manager(tmp_path, provider)
    messages = (ChatMessage("user", "one"), ChatMessage("assistant", "two"))

    statuses, outcome = consume(manager.compact(messages))

    assert [status.kind for status in statuses] == [
        ContextStatusKind.COMPACTION_STARTED,
        ContextStatusKind.NO_COMPACTION_NEEDED,
    ]
    assert outcome.messages == messages
    assert outcome.changed is False
    assert provider.calls == []
    archive.close()


def test_manual_request_uses_8192_output_no_tools_and_explicit_margin(
    tmp_path: Path,
) -> None:
    path = ".mewcode/context/session/history-000001.json"
    provider = ScriptedAsyncProvider(
        [[ProviderTextDelta(summary_response(path))]]
    )
    archive, manager = started_manager(tmp_path, provider)

    statuses, outcome = consume(manager.compact(large_history()))

    assert outcome.changed is True
    assert statuses[-1].kind is ContextStatusKind.COMPACTION_COMPLETED
    assert provider.calls[0].max_output_tokens == 8_192
    assert provider.calls[0].tools is None
    archive.close()


def test_context_cancel_rolls_back_without_counting_failure(tmp_path: Path) -> None:
    class BlockingProvider(ScriptedAsyncProvider):
        def __init__(self) -> None:
            super().__init__([])
            self.started = asyncio.Event()

        async def stream_reply(self, model_request):
            self.calls.append(model_request)
            self.started.set()
            await asyncio.Event().wait()
            if False:
                yield ProviderTextDelta("")

    async def scenario() -> None:
        provider = BlockingProvider()
        archive, manager = started_manager(tmp_path, provider)
        operation = manager.compact(large_history())
        consumer = asyncio.create_task(collect_async(operation.statuses()))
        await provider.started.wait()

        await operation.cancel()

        assert consumer.cancelled()
        assert manager.consecutive_failures == 0
        assert archive.session_dir is not None
        assert list(archive.session_dir.glob("history-*.json")) == []
        archive.close()

    asyncio.run(scenario())


def test_operation_is_single_use_and_outcome_is_guarded(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([])
    archive, manager = started_manager(tmp_path, provider)
    operation = manager.prepare(request((ChatMessage("user", "hello"),)))

    with pytest.raises(ContextError, match="not completed"):
        _ = operation.outcome
    consume(operation)
    with pytest.raises(ContextError, match="only be consumed once"):
        asyncio.run(collect_async(operation.statuses()))
    archive.close()


def test_preserve_prefix_checks_capacity_without_compaction(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([])
    archive, manager = started_manager(tmp_path, provider)
    small = request((ChatMessage("user", "hello"),))

    statuses, outcome = consume(manager.prepare(small, preserve_prefix=True))
    assert statuses == []
    assert outcome.request is small
    assert outcome.messages is small.messages

    large = request(large_history())
    statuses, outcome = consume(manager.prepare(large, preserve_prefix=True))
    assert statuses == []
    assert outcome.request is None
    assert outcome.messages is large.messages
    assert outcome.failure_kind.value == "capacity"
    assert provider.calls == []
    archive.close()


def test_task_archives_skip_process_wide_stale_cleanup(tmp_path: Path) -> None:
    stale = tmp_path / ".mewcode" / "context" / "stale"
    stale.mkdir(parents=True)
    first = ContextArchive(tmp_path, session_id_factory=lambda: "task-a")
    second = ContextArchive(tmp_path, session_id_factory=lambda: "task-b")

    first.start(skip_stale_cleanup=True)
    second.start(skip_stale_cleanup=True)

    assert stale.exists()
    assert first.session_dir is not None and first.session_dir.exists()
    assert second.session_dir is not None and second.session_dir.exists()
    first.close()
    assert second.session_dir is not None and second.session_dir.exists()
    second.close()

    root = ContextArchive(tmp_path, session_id_factory=lambda: "root")
    root.start()
    assert not stale.exists()
    root.close()
