from __future__ import annotations

from dataclasses import replace
from collections.abc import Sequence

from mewcode.tools import ToolExecution, ToolResult, serialize_tool_result

from .archive import ContextArchive
from .estimator import estimate_text_tokens, take_prefix, take_suffix
from .models import (
    ArchiveKind,
    ArchiveRecord,
    ContextArchiveError,
    ContextConfig,
    ContextStatus,
    ContextStatusKind,
    ToolCompactionResult,
)


class ToolResultCompactor:
    def __init__(self, archive: ContextArchive, config: ContextConfig) -> None:
        self._archive = archive
        self._config = config

    def compact(
        self, executions: Sequence[ToolExecution]
    ) -> ToolCompactionResult:
        original = tuple(executions)
        payloads = [serialize_tool_result(item.result) for item in original]
        sizes = [estimate_text_tokens(payload) for payload in payloads]
        selected = {
            index
            for index, size in enumerate(sizes)
            if size > self._config.single_tool_tokens
        }

        def simulated_total(indices: set[int]) -> int:
            return sum(
                self._simulated_placeholder_tokens(original[index], payloads[index], sizes[index])
                if index in indices
                else sizes[index]
                for index in range(len(original))
            )

        candidates = sorted(
            (index for index in range(len(original)) if index not in selected),
            key=lambda index: (-sizes[index], original[index].index),
        )
        while simulated_total(selected) > self._config.tool_batch_tokens and candidates:
            selected.add(candidates.pop(0))

        if not selected:
            return ToolCompactionResult(original, (), ())

        records: list[ArchiveRecord] = []
        records_by_index: dict[int, ArchiveRecord] = {}
        replacements: dict[int, ToolExecution] = {}
        try:
            for index in sorted(selected):
                execution = original[index]
                record = self._archive.write_tool_result(execution)
                records.append(record)
                records_by_index[index] = record
                replacements[index] = replace(
                    execution,
                    result=self._archived_result(
                        execution,
                        payloads[index],
                        sizes[index],
                        record,
                        self._config.tool_preview_tokens,
                    ),
                )
        except ContextArchiveError:
            for record in records:
                self._archive.discard(record)
            raise

        preview_budget = self._config.tool_preview_tokens
        compacted = tuple(
            replacements.get(index, execution)
            for index, execution in enumerate(original)
        )
        while self._batch_tokens(compacted) > self._config.tool_batch_tokens and preview_budget > 0:
            excess = self._batch_tokens(compacted) - self._config.tool_batch_tokens
            preview_budget = max(
                0,
                preview_budget - max(1, (excess + len(selected) - 1) // len(selected)),
            )
            for index in sorted(selected):
                replacements[index] = replace(
                    original[index],
                    result=self._archived_result(
                        original[index],
                        payloads[index],
                        sizes[index],
                        records_by_index[index],
                        preview_budget,
                    ),
                )
            compacted = tuple(
                replacements.get(index, execution)
                for index, execution in enumerate(original)
            )

        statuses = tuple(
            ContextStatus(
                ContextStatusKind.TOOL_ARCHIVED,
                f"Archived a tool result at {record.relative_path}.",
            )
            for _index, record in zip(sorted(selected), records, strict=True)
        )
        return ToolCompactionResult(compacted, tuple(records), statuses)

    def _archived_result(
        self,
        execution: ToolExecution,
        payload: str,
        original_tokens: int,
        record: ArchiveRecord,
        preview_budget: int,
    ) -> ToolResult:
        head, tail = _preview_parts(payload, preview_budget)
        preview = head
        if tail:
            preview = f"{head}\n...\n{tail}" if head else tail
        content = (
            "[tool result archived]\n"
            f"tool: {execution.request.name}\n"
            f"call_id: {execution.request.id}\n"
            f"estimated_tokens: {original_tokens}\n"
            f"path: {record.relative_path}\n"
            "preview:\n"
            f"{preview}"
        )
        return ToolResult(
            ok=execution.result.ok,
            tool_name=execution.result.tool_name,
            content=content,
            error=(
                "Full tool error archived; read the path in content for details."
                if not execution.result.ok
                else None
            ),
            metadata={
                "archived": True,
                "archive_path": record.relative_path,
                "original_estimated_tokens": original_tokens,
                "tool_call_id": execution.request.id,
            },
        )

    def _simulated_placeholder_tokens(
        self,
        execution: ToolExecution,
        payload: str,
        original_tokens: int,
    ) -> int:
        record = ArchiveRecord(
            kind=ArchiveKind.TOOL_RESULT,
            relative_path=".mewcode/context/session/tool-000000.json",
            estimated_tokens=original_tokens,
            sequence=0,
        )
        return estimate_text_tokens(
            serialize_tool_result(
                self._archived_result(
                    execution,
                    payload,
                    original_tokens,
                    record,
                    self._config.tool_preview_tokens,
                )
            )
        )

    def _batch_tokens(self, executions: Sequence[ToolExecution]) -> int:
        return sum(
            estimate_text_tokens(serialize_tool_result(execution.result))
            for execution in executions
        )


def _preview_parts(payload: str, token_budget: int) -> tuple[str, str]:
    if token_budget <= 0:
        return "", ""
    head_budget = token_budget // 2
    tail_budget = token_budget - head_budget
    head = take_prefix(payload, head_budget)
    remainder = payload[len(head) :]
    tail = take_suffix(remainder, tail_budget)

    head_tokens = estimate_text_tokens(head)
    tail_tokens = estimate_text_tokens(tail)
    unused = token_budget - head_tokens - tail_tokens
    if unused > 0 and len(head) + len(tail) < len(payload):
        head = take_prefix(payload[: len(payload) - len(tail)], head_tokens + unused)
        unused = token_budget - estimate_text_tokens(head) - tail_tokens
    if unused > 0 and len(head) + len(tail) < len(payload):
        tail = take_suffix(payload[len(head) :], tail_tokens + unused)
    return head, tail
