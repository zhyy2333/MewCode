from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.context import (
    ContextArchive,
    ContextArchiveError,
    ContextConfig,
    ToolResultCompactor,
    estimate_text_tokens,
)
from mewcode.tools import ToolExecution, ToolResult, serialize_tool_result

from tests.fakes import tool_call


def execution(index: int, size: int, *, name: str | None = None) -> ToolExecution:
    tool_name = name or f"tool_{index}"
    content = f"HEAD-{tool_name}-" + ("x" * size) + f"-TAIL-{tool_name}"
    return ToolExecution(
        index=index,
        request=tool_call(f"call-{index}", tool_name),
        result=ToolResult(True, tool_name, content),
    )


def started_compactor(tmp_path: Path) -> tuple[ContextArchive, ToolResultCompactor]:
    archive = ContextArchive(tmp_path, session_id_factory=lambda: "session")
    archive.start()
    return archive, ToolResultCompactor(archive, ContextConfig(128_000))


def test_single_large_result_is_archived_with_bounded_head_tail_preview(
    tmp_path: Path,
) -> None:
    archive, compactor = started_compactor(tmp_path)
    item = execution(0, 40_000)

    result = compactor.compact([item])

    compacted = result.executions[0].result
    assert compacted.metadata["archived"] is True
    assert "HEAD-tool_0" in compacted.content
    assert "TAIL-tool_0" in compacted.content
    assert len(result.archives) == 1
    assert len(result.statuses) == 1
    assert estimate_text_tokens(serialize_tool_result(compacted)) <= 1_100
    assert (tmp_path / result.archives[0].relative_path).exists()
    archive.close()


def test_batch_deterministic_selection_archives_largest_until_under_budget(
    tmp_path: Path,
) -> None:
    archive, compactor = started_compactor(tmp_path)
    items = [execution(5, 24_000), execution(2, 24_000), execution(3, 24_000)]

    result = compactor.compact(items)

    archived = [
        item.request.name
        for item in result.executions
        if item.result.metadata.get("archived")
    ]
    total = sum(
        estimate_text_tokens(serialize_tool_result(item.result))
        for item in result.executions
    )
    assert archived == ["tool_2", "tool_3"]
    assert total <= 12_000
    archive.close()


def test_small_batch_is_left_unchanged(tmp_path: Path) -> None:
    archive, compactor = started_compactor(tmp_path)
    items = (execution(0, 2_000), execution(1, 2_000))

    result = compactor.compact(items)

    assert result.executions == items
    assert result.archives == ()
    assert result.statuses == ()
    archive.close()


def test_atomic_archival_failure_rolls_back_the_entire_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, compactor = started_compactor(tmp_path)
    items = [execution(0, 40_000), execution(1, 40_000)]
    real_write = archive.write_tool_result
    calls = 0

    def fail_second(item: ToolExecution):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ContextArchiveError("simulated failure")
        return real_write(item)

    monkeypatch.setattr(archive, "write_tool_result", fail_second)

    with pytest.raises(ContextArchiveError, match="simulated failure"):
        compactor.compact(items)

    assert archive.session_dir is not None
    assert list(archive.session_dir.glob("tool-*.json")) == []
    archive.close()


def test_single_threshold_uses_strictly_greater_than_original_estimate(
    tmp_path: Path,
) -> None:
    item = execution(0, 12_000)
    size = estimate_text_tokens(serialize_tool_result(item.result))

    exact_archive = ContextArchive(tmp_path / "exact", session_id_factory=lambda: "s")
    exact_archive.start()
    exact = ToolResultCompactor(
        exact_archive,
        ContextConfig(
            128_000,
            single_tool_tokens=size,
            tool_batch_tokens=size + 100,
        ),
    ).compact([item])
    assert exact.archives == ()
    exact_archive.close()

    over_archive = ContextArchive(tmp_path / "over", session_id_factory=lambda: "s")
    over_archive.start()
    over = ToolResultCompactor(
        over_archive,
        ContextConfig(
            128_000,
            single_tool_tokens=size - 1,
            tool_batch_tokens=size + 100,
        ),
    ).compact([item])
    assert len(over.archives) == 1
    over_archive.close()


def test_security_tool_content_and_name_do_not_control_paths_or_status(
    tmp_path: Path,
) -> None:
    secret = "SECRET-VALUE-DO-NOT-PRINT"
    item = execution(0, 40_000, name=f"../bad/{secret}\n")
    archive, compactor = started_compactor(tmp_path)

    result = compactor.compact([item])

    record = result.archives[0]
    assert record.relative_path.endswith("tool-000001.json")
    assert secret not in record.relative_path
    assert secret not in result.statuses[0].message
    assert "../bad" not in result.statuses[0].message
    assert (tmp_path / record.relative_path).parent == archive.session_dir
    archive.close()
