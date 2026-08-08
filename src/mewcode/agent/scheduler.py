from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from enum import Enum, auto

from mewcode.tools import (
    ToolCallRequest,
    ToolExecution,
    ToolRegistry,
    ToolResult,
    ToolSafety,
)

from .events import AgentEvent, AgentProgress, AgentToolResult


class ToolScheduleStateError(RuntimeError):
    pass


class _State(Enum):
    NEW = auto()
    RUNNING = auto()
    COMPLETE = auto()
    FAILED = auto()


class ToolSchedule:
    def __init__(
        self,
        run_id: str,
        iteration: int,
        requests: Sequence[ToolCallRequest],
        registry: ToolRegistry,
        max_read_concurrency: int,
    ) -> None:
        self._run_id = run_id
        self._iteration = iteration
        self._requests = tuple(requests)
        self._registry = registry
        self._max_read_concurrency = max_read_concurrency
        self._state = _State.NEW
        self._executions: tuple[ToolExecution, ...] | None = None
        self._cancel_requested = asyncio.Event()
        self._active_tasks: set[asyncio.Task[ToolExecution]] = set()

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._state is not _State.NEW:
            raise ToolScheduleStateError("A tool schedule can only be consumed once.")
        self._state = _State.RUNNING
        completed: list[ToolExecution] = []
        total = len(self._requests)
        try:
            for batch in self._partition():
                yield AgentProgress(
                    run_id=self._run_id,
                    iteration=self._iteration,
                    phase="tool_batch_started",
                    completed=len(completed),
                    total=total,
                    message=f"running {len(batch)} tool call(s)",
                )
                if self._is_read_batch(batch):
                    async for execution in self._run_read_batch(batch):
                        completed.append(execution)
                        yield self._result_event(execution)
                else:
                    index, request = batch[0]
                    execution = await self._run_serial(index, request)
                    completed.append(execution)
                    yield self._result_event(execution)
                yield AgentProgress(
                    run_id=self._run_id,
                    iteration=self._iteration,
                    phase="tool_batch_completed",
                    completed=len(completed),
                    total=total,
                    message="tool batch completed",
                )
        except BaseException:
            self._state = _State.FAILED
            await self._cancel_tasks()
            raise

        self._executions = tuple(sorted(completed, key=lambda item: item.index))
        self._state = _State.COMPLETE

    async def cancel(self) -> None:
        self._cancel_requested.set()
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    @property
    def executions(self) -> tuple[ToolExecution, ...]:
        if self._state is not _State.COMPLETE or self._executions is None:
            raise ToolScheduleStateError("The tool schedule did not complete successfully.")
        return self._executions

    @property
    def cancelled(self) -> bool:
        return self._cancel_requested.is_set()

    def _partition(self) -> list[list[tuple[int, ToolCallRequest]]]:
        batches: list[list[tuple[int, ToolCallRequest]]] = []
        read_batch: list[tuple[int, ToolCallRequest]] = []
        for index, request in enumerate(self._requests):
            tool = self._registry.get(request.name)
            if tool is not None and tool.safety is ToolSafety.READ_ONLY:
                read_batch.append((index, request))
                continue
            if read_batch:
                batches.append(read_batch)
                read_batch = []
            batches.append([(index, request)])
        if read_batch:
            batches.append(read_batch)
        return batches

    def _is_read_batch(self, batch: list[tuple[int, ToolCallRequest]]) -> bool:
        if not batch:
            return False
        tool = self._registry.get(batch[0][1].name)
        return tool is not None and tool.safety is ToolSafety.READ_ONLY

    async def _run_read_batch(
        self, batch: list[tuple[int, ToolCallRequest]]
    ) -> AsyncIterator[ToolExecution]:
        semaphore = asyncio.Semaphore(self._max_read_concurrency)
        tasks = {
            asyncio.create_task(self._run_one(index, request, semaphore))
            for index, request in batch
        }
        yielded_indexes: set[int] = set()
        self._active_tasks.update(tasks)
        try:
            for future in asyncio.as_completed(tasks):
                execution = await future
                yielded_indexes.add(execution.index)
                yield execution
                if self._cancel_requested.is_set():
                    await self._cancel_tasks()
        except asyncio.CancelledError:
            self._cancel_requested.set()
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if (
                    isinstance(result, ToolExecution)
                    and result.index not in yielded_indexes
                ):
                    yielded_indexes.add(result.index)
                    yield result
        finally:
            self._active_tasks.difference_update(tasks)

    async def _run_serial(
        self, index: int, request: ToolCallRequest
    ) -> ToolExecution:
        task = asyncio.create_task(self._run_one(index, request, None))
        self._active_tasks.add(task)
        try:
            return await task
        finally:
            self._active_tasks.discard(task)

    async def _run_one(
        self,
        index: int,
        request: ToolCallRequest,
        semaphore: asyncio.Semaphore | None,
    ) -> ToolExecution:
        try:
            if self._cancel_requested.is_set():
                raise asyncio.CancelledError
            if semaphore is None:
                result = await self._registry.execute(request)
            else:
                async with semaphore:
                    if self._cancel_requested.is_set():
                        raise asyncio.CancelledError
                    result = await self._registry.execute(request)
        except asyncio.CancelledError:
            self._cancel_requested.set()
            result = _cancelled_result(request)
        return ToolExecution(index=index, request=request, result=result)

    async def _cancel_tasks(self) -> None:
        self._cancel_requested.set()
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    def _result_event(self, execution: ToolExecution) -> AgentToolResult:
        return AgentToolResult(
            run_id=self._run_id,
            iteration=self._iteration,
            execution=execution,
        )


class ToolScheduler:
    def __init__(self, max_read_concurrency: int = 4) -> None:
        if max_read_concurrency < 1:
            raise ValueError("max_read_concurrency must be at least 1")
        self._max_read_concurrency = max_read_concurrency

    def schedule(
        self,
        run_id: str,
        iteration: int,
        requests: Sequence[ToolCallRequest],
        registry: ToolRegistry,
    ) -> ToolSchedule:
        return ToolSchedule(
            run_id=run_id,
            iteration=iteration,
            requests=requests,
            registry=registry,
            max_read_concurrency=self._max_read_concurrency,
        )


def _cancelled_result(request: ToolCallRequest) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=request.name,
        content="",
        error="Tool call cancelled.",
        metadata={"tool_call_id": request.id, "cancelled": True},
    )
