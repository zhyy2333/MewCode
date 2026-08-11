from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.context import (
    BOUNDARY_MESSAGE,
    CompactionMode,
    ContextArchive,
    ContextCapacityError,
    ContextCompactionError,
    ContextConfig,
    HistoryCompactor,
    RecentHistorySelector,
    SummaryCollector,
    SummaryParser,
    SummaryPromptBuilder,
    TokenEstimator,
)
from mewcode.providers import (
    ChatMessage,
    MessageKind,
    ProviderFinished,
    ProviderFinishReason,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)

from tests.fakes import ScriptedAsyncProvider, tool_call


def config(**overrides: int) -> ContextConfig:
    values = {
        "context_window": 128_000,
        "recent_tokens": 10,
        "recent_messages": 2,
    }
    values.update(overrides)
    return ContextConfig(**values)


def formal_summary(path: str) -> str:
    sections = (
        ("当前目标", "继续实现上下文管理。"),
        ("仍有效的用户原始约束", "逐字约束"),
        ("关键决策及理由", "采用两层压缩以控制容量。"),
        ("已完成工作", "已完成估算器。"),
        ("当前代码与文件状态", "工作区存在上下文包。"),
        ("未解决问题与风险", "无"),
        ("下一步行动", "接入主循环。"),
        ("存盘记录索引", path),
    )
    body = "\n\n".join(
        f"## {index}. {title}\n{content}"
        for index, (title, content) in enumerate(sections, start=1)
    )
    return (
        "<analysis_draft>private reasoning</analysis_draft>\n"
        f"<formal_summary>{body}</formal_summary>"
    )


def test_recent_selector_meets_both_targets_and_keeps_groups_atomic() -> None:
    selector = RecentHistorySelector(TokenEstimator(), config())
    messages = (
        ChatMessage("user", "old-1"),
        ChatMessage("assistant", "old-2"),
        ChatMessage("assistant", "x" * 80, group_id="tools"),
        ChatMessage("tool", "result", group_id="tools"),
        ChatMessage("user", "last"),
    )

    selection = selector.select(messages)

    assert selection.can_compact is True
    assert selection.early == messages[:2]
    assert selection.recent == messages[2:]


def test_rolling_summary_is_replaced_only_when_new_ordinary_history_is_early() -> None:
    selector = RecentHistorySelector(TokenEstimator(), config(recent_tokens=1))
    old_summary = ChatMessage("system", "old summary", MessageKind.SUMMARY)
    old_boundary = ChatMessage("system", "old boundary", MessageKind.BOUNDARY)
    messages = (
        old_summary,
        old_boundary,
        ChatMessage("user", "old"),
        ChatMessage("assistant", "recent"),
        ChatMessage("user", "latest"),
    )

    selection = selector.select(messages)

    assert selection.early == messages[:3]
    assert selection.recent == messages[3:]


def test_selector_reports_noop_when_every_ordinary_message_is_recent() -> None:
    selector = RecentHistorySelector(TokenEstimator(), config(recent_tokens=10_000))
    messages = (ChatMessage("user", "one"), ChatMessage("assistant", "two"))

    selection = selector.select(messages)

    assert selection.can_compact is False
    assert selection.early == ()
    assert selection.recent == messages


def test_summary_prompt_has_fixed_contract_and_no_tools() -> None:
    from mewcode.context import ArchiveKind, ArchiveRecord

    request = SummaryPromptBuilder(config()).build(
        [ChatMessage("user", "必须原样保留")],
        ArchiveRecord(ArchiveKind.HISTORY, ".mewcode/context/s/history.json", 10, 1),
    )

    assert request.tools is None
    assert request.max_output_tokens == 8_192
    assert "禁止调用任何工具" in request.prompt.stable_system
    assert "<analysis_draft>" in request.prompt.stable_system
    assert "<formal_summary>" in request.prompt.stable_system
    assert "逐字保留" in request.prompt.stable_system
    assert "不得臆测" in request.prompt.stable_system
    assert "## 8. 存盘记录索引" in request.prompt.stable_system
    assert ".mewcode/context/s/history.json" in request.messages[0].content


def test_parser_returns_only_formal_summary() -> None:
    parsed = SummaryParser().parse(formal_summary("history.json"))

    assert "private reasoning" not in parsed
    assert "<formal_summary>" not in parsed
    assert parsed.startswith("## 1. 当前目标")


@pytest.mark.parametrize(
    "response",
    [
        "",
        "<formal_summary>bad</formal_summary>",
        formal_summary("history.json").replace("## 4. 已完成工作", ""),
        formal_summary("history.json").replace("## 6. 未解决问题与风险\n无", "## 6. 未解决问题与风险\n"),
        formal_summary("history.json") + " trailing",
    ],
)
def test_parser_rejects_invalid_or_incomplete_responses(response: str) -> None:
    with pytest.raises(ContextCompactionError):
        SummaryParser().parse(response)


def test_summary_collector_is_private_and_rejects_tool_calls() -> None:
    async def scenario() -> None:
        provider = ScriptedAsyncProvider(
            [
                [
                    ProviderTextDelta("secret"),
                    ProviderUsage(TokenUsage(input_tokens=7, output_tokens=3)),
                    ProviderFinished(ProviderFinishReason.NATURAL),
                ],
                [ProviderToolCall(tool_call("call", "read_file"))],
            ]
        )
        collector = SummaryCollector()

        text, usage = await collector.collect(
            provider.stream_reply(None)  # type: ignore[arg-type]
        )
        assert text == "secret"
        assert usage.input_tokens == 7
        with pytest.raises(ContextCompactionError, match="tool call"):
            await collector.collect(
                provider.stream_reply(None)  # type: ignore[arg-type]
            )

    asyncio.run(scenario())


def test_history_compaction_commits_summary_boundary_and_original_recent_messages(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = ".mewcode/context/session/history-000001.json"
        provider = ScriptedAsyncProvider(
            [[ProviderTextDelta(formal_summary(path))]]
        )
        archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
        archive.start()
        compactor = HistoryCompactor(provider, archive, config(), TokenEstimator())
        messages = (
            ChatMessage("user", "old user constraint"),
            ChatMessage("assistant", "old work"),
            ChatMessage("user", "x" * 80),
            ChatMessage("assistant", "recent answer"),
            ChatMessage("user", "latest request"),
        )

        result = await compactor.compact(messages, CompactionMode.MANUAL)

        assert result.changed is True
        assert result.messages[0].kind is MessageKind.SUMMARY
        assert "private reasoning" not in result.messages[0].content
        assert result.messages[1] == ChatMessage(
            "system", BOUNDARY_MESSAGE, MessageKind.BOUNDARY
        )
        assert result.messages[2:] == messages[3:]
        assert result.archive is not None
        assert (tmp_path / result.archive.relative_path).exists()
        assert provider.calls[0].tools is None
        assert provider.calls[0].max_output_tokens == 8_192
        archive.close()

    asyncio.run(scenario())


def test_history_compaction_rolls_back_archive_and_history_on_failure(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        provider = ScriptedAsyncProvider([[ProviderTextDelta("invalid")]])
        archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
        archive.start()
        compactor = HistoryCompactor(provider, archive, config(), TokenEstimator())
        messages = tuple(
            ChatMessage("user", f"message-{index}") for index in range(5)
        )

        with pytest.raises(ContextCompactionError):
            await compactor.compact(messages, CompactionMode.MANUAL)

        assert archive.session_dir is not None
        assert list(archive.session_dir.glob("history-*.json")) == []
        assert messages == tuple(messages)
        archive.close()

    asyncio.run(scenario())


def test_summary_capacity_is_checked_before_provider_call(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = ScriptedAsyncProvider([])
        archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
        archive.start()
        tiny = config(context_window=22_000, recent_tokens=1, recent_messages=1)
        compactor = HistoryCompactor(provider, archive, tiny, TokenEstimator())
        messages = (
            ChatMessage("user", "x" * 100_000),
            ChatMessage("assistant", "recent"),
        )

        with pytest.raises(ContextCapacityError):
            await compactor.compact(messages, CompactionMode.MANUAL)

        assert provider.calls == []
        assert archive.session_dir is not None
        assert list(archive.session_dir.glob("history-*.json")) == []
        archive.close()

    asyncio.run(scenario())
