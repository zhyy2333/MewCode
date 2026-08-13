from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto

from mewcode.providers import ChatMessage, LLMProvider, ModelRequest, TokenUsage
from mewcode.tools import ToolExecution
from mewcode.hooks import HookEvent, HookRuntime, make_event

from .archive import ContextArchive
from .estimator import TokenEstimator
from .models import (
    CompactionCircuitBreaker,
    CompactionMode,
    ContextConfig,
    ContextError,
    ContextFailureKind,
    ContextPreparation,
    ContextRuntimeStatus,
    ContextStatus,
    ContextStatusKind,
    RequestFootprint,
    ToolCompactionResult,
)
from .summary import HistoryCompactor
from .tool_results import ToolResultCompactor


class _OperationStateKind(Enum):
    NEW = auto()
    ACTIVE = auto()
    COMPLETE = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass
class _OperationState:
    outcome: ContextPreparation | None = None


class ContextOperation:
    def __init__(
        self,
        source: AsyncIterator[ContextStatus],
        state: _OperationState,
    ) -> None:
        self._source = source
        self._shared = state
        self._state = _OperationStateKind.NEW
        self._consumer: asyncio.Task[object] | None = None

    async def statuses(self) -> AsyncIterator[ContextStatus]:
        if self._state is not _OperationStateKind.NEW:
            raise ContextError("A context operation can only be consumed once.")
        self._state = _OperationStateKind.ACTIVE
        current = asyncio.current_task()
        self._consumer = current
        try:
            async for status in self._source:
                yield status
        except asyncio.CancelledError:
            self._state = _OperationStateKind.CANCELLED
            raise
        except BaseException:
            self._state = _OperationStateKind.FAILED
            raise
        else:
            if self._shared.outcome is None:
                self._state = _OperationStateKind.FAILED
                raise ContextError("The context operation did not produce an outcome.")
            self._state = _OperationStateKind.COMPLETE
        finally:
            self._consumer = None

    @property
    def outcome(self) -> ContextPreparation:
        if (
            self._state is not _OperationStateKind.COMPLETE
            or self._shared.outcome is None
        ):
            raise ContextError("The context operation has not completed successfully.")
        return self._shared.outcome

    async def cancel(self) -> None:
        consumer = self._consumer
        if consumer is None or consumer is asyncio.current_task():
            return
        consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass


class ContextManager:
    def __init__(
        self,
        provider: LLMProvider,
        archive: ContextArchive,
        config: ContextConfig,
        hook_runtime: HookRuntime | None = None,
    ) -> None:
        self._archive = archive
        self._config = config
        self._estimator = TokenEstimator()
        self._tool_compactor = ToolResultCompactor(archive, config)
        self._history_compactor = HistoryCompactor(
            provider,
            archive,
            config,
            self._estimator,
        )
        self._breaker = CompactionCircuitBreaker(config.failure_limit)
        self._hook_runtime = hook_runtime

    @property
    def consecutive_failures(self) -> int:
        return self._breaker.consecutive_failures

    @property
    def automatic_compaction_disabled(self) -> bool:
        return self._breaker.is_open

    def status(self) -> ContextRuntimeStatus:
        return ContextRuntimeStatus(
            automatic_compaction_enabled=not self._breaker.is_open,
            consecutive_failures=self._breaker.consecutive_failures,
        )

    def compact_tool_results(
        self,
        executions: Sequence[ToolExecution],
    ) -> ToolCompactionResult:
        return self._tool_compactor.compact(executions)

    def prepare(self, request: ModelRequest) -> ContextOperation:
        state = _OperationState()
        return ContextOperation(self._prepare_automatic(request, state), state)

    def compact(self, messages: Sequence[ChatMessage]) -> ContextOperation:
        state = _OperationState()
        return ContextOperation(self._prepare_manual(tuple(messages), state), state)

    def observe_usage(
        self,
        footprint: RequestFootprint | None,
        usage: TokenUsage,
    ) -> None:
        if footprint is not None:
            self._estimator.observe(footprint, usage)

    def close(self) -> tuple[ContextStatus, ...]:
        return self._archive.close()

    def reset_runtime_state(self) -> None:
        self._estimator = TokenEstimator()
        self._breaker = CompactionCircuitBreaker(self._config.failure_limit)

    async def _prepare_automatic(
        self,
        request: ModelRequest,
        state: _OperationState,
    ) -> AsyncIterator[ContextStatus]:
        estimate = self._estimator.estimate(request)
        boundary = self._main_boundary(request)
        if estimate.input_tokens < boundary:
            state.outcome = ContextPreparation(
                request,
                request.messages,
                estimate.footprint,
            )
            return

        if self._breaker.is_open:
            message = (
                "Automatic context compaction is disabled after three consecutive "
                "failures. This request risks overflowing the context window; run "
                "/compact to retry explicitly."
            )
            yield ContextStatus(ContextStatusKind.CIRCUIT_OPEN, message)
            state.outcome = ContextPreparation(
                None,
                request.messages,
                estimate.footprint,
                error=message,
                failure_kind=ContextFailureKind.CAPACITY,
            )
            return

        yield ContextStatus(
            ContextStatusKind.COMPACTION_STARTED,
            "Automatically compacting earlier conversation history.",
        )
        await self._compact_hook(
            HookEvent.COMPACT_BEFORE, "automatic", "started", len(request.messages)
        )
        try:
            compacted = await self._history_compactor.compact(
                request.messages,
                CompactionMode.AUTOMATIC,
            )
        except asyncio.CancelledError:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER,
                "automatic",
                "cancelled",
                len(request.messages),
            )
            raise
        except ContextError:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER,
                "automatic",
                "failure",
                len(request.messages),
                error="compaction failed",
            )
            async for status in self._record_failure():
                yield status
            message = "Automatic context compaction failed; active history was unchanged."
            state.outcome = ContextPreparation(
                None,
                request.messages,
                estimate.footprint,
                error=message,
                failure_kind=ContextFailureKind.COMPACTION,
            )
            return

        if not compacted.changed:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER,
                "automatic",
                "failure",
                len(request.messages),
                len(compacted.messages),
                changed=False,
            )
            message = (
                "The request is near the context limit, but no earlier history can be "
                "compacted safely."
            )
            yield ContextStatus(ContextStatusKind.COMPACTION_FAILED, message)
            state.outcome = ContextPreparation(
                None,
                request.messages,
                estimate.footprint,
                error=message,
                failure_kind=ContextFailureKind.CAPACITY,
            )
            return

        recovered = self._breaker.record_success()
        if recovered:
            yield ContextStatus(
                ContextStatusKind.CIRCUIT_RECOVERED,
                "Context compaction recovered; automatic compaction is enabled.",
            )
        yield ContextStatus(
            ContextStatusKind.COMPACTION_COMPLETED,
            "Earlier conversation history was compacted successfully.",
            compacted.usage,
        )
        rebuilt = replace(request, messages=compacted.messages)
        rebuilt_estimate = self._estimator.estimate(rebuilt)
        if rebuilt_estimate.input_tokens >= boundary:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER,
                "automatic",
                "failure",
                len(request.messages),
                len(compacted.messages),
                changed=True,
                error="compacted request still exceeds capacity",
            )
            message = (
                "The compacted request still cannot fit within the safe context boundary."
            )
            yield ContextStatus(ContextStatusKind.COMPACTION_FAILED, message)
            state.outcome = ContextPreparation(
                None,
                compacted.messages,
                rebuilt_estimate.footprint,
                usage=compacted.usage,
                changed=True,
                error=message,
                failure_kind=ContextFailureKind.CAPACITY,
            )
            return
        state.outcome = ContextPreparation(
            rebuilt,
            compacted.messages,
            rebuilt_estimate.footprint,
            usage=compacted.usage,
            changed=True,
        )
        await self._compact_hook(
            HookEvent.COMPACT_AFTER,
            "automatic",
            "success",
            len(request.messages),
            len(compacted.messages),
            changed=True,
        )

    async def _prepare_manual(
        self,
        messages: tuple[ChatMessage, ...],
        state: _OperationState,
    ) -> AsyncIterator[ContextStatus]:
        yield ContextStatus(
            ContextStatusKind.COMPACTION_STARTED,
            "Explicitly compacting earlier conversation history.",
        )
        await self._compact_hook(
            HookEvent.COMPACT_BEFORE, "manual", "started", len(messages)
        )
        try:
            compacted = await self._history_compactor.compact(
                messages,
                CompactionMode.MANUAL,
            )
        except asyncio.CancelledError:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER, "manual", "cancelled", len(messages)
            )
            raise
        except ContextError:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER,
                "manual",
                "failure",
                len(messages),
                error="compaction failed",
            )
            async for status in self._record_failure():
                yield status
            message = "Explicit context compaction failed; active history was unchanged."
            state.outcome = ContextPreparation(
                None,
                messages,
                None,
                error=message,
                failure_kind=ContextFailureKind.COMPACTION,
            )
            return

        if not compacted.changed:
            await self._compact_hook(
                HookEvent.COMPACT_AFTER,
                "manual",
                "success",
                len(messages),
                len(compacted.messages),
                changed=False,
            )
            yield ContextStatus(
                ContextStatusKind.NO_COMPACTION_NEEDED,
                "No earlier conversation history needs compaction.",
            )
            state.outcome = ContextPreparation(None, messages, None)
            return

        recovered = self._breaker.record_success()
        if recovered:
            yield ContextStatus(
                ContextStatusKind.CIRCUIT_RECOVERED,
                "Context compaction recovered; automatic compaction is enabled.",
            )
        yield ContextStatus(
            ContextStatusKind.COMPACTION_COMPLETED,
            "Earlier conversation history was compacted successfully.",
            compacted.usage,
        )
        state.outcome = ContextPreparation(
            None,
            compacted.messages,
            None,
            usage=compacted.usage,
            changed=True,
        )
        await self._compact_hook(
            HookEvent.COMPACT_AFTER,
            "manual",
            "success",
            len(messages),
            len(compacted.messages),
            changed=True,
        )

    async def _compact_hook(
        self,
        event: HookEvent,
        mode: str,
        status: str,
        before: int,
        after: int | None = None,
        *,
        changed: bool | None = None,
        error: str | None = None,
    ) -> None:
        if self._hook_runtime is None:
            return
        values: dict[str, object] = {
            "mode": mode,
            "status": status,
            "message_count_before": before,
        }
        if after is not None:
            values["message_count_after"] = after
        if changed is not None:
            values["changed"] = changed
        if error is not None:
            values["error"] = error
        await self._hook_runtime.dispatch(
            make_event(
                event,
                workspace=self._hook_runtime.workspace,
                session_id=self._hook_runtime.session_id,
                resumed=self._hook_runtime.resumed,
                values={
                    "turn": {
                        "id": self._hook_runtime.scope.get("turn_id"),
                        "mode": self._hook_runtime.scope.get("mode"),
                    },
                    "compaction": values,
                },
            )
        )

    async def _record_failure(self) -> AsyncIterator[ContextStatus]:
        self._breaker.record_failure()
        yield ContextStatus(
            ContextStatusKind.COMPACTION_FAILED,
            "Context compaction failed; active history was left unchanged.",
        )
        if self._breaker.is_open:
            yield ContextStatus(
                ContextStatusKind.CIRCUIT_OPEN,
                "Automatic context compaction is now disabled after three failures. "
                "Use /compact for one explicit retry.",
            )

    def _main_boundary(self, request: ModelRequest) -> int:
        return (
            self._config.context_window
            - request.max_output_tokens
            - self._config.automatic_margin
        )
