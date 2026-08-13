from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from enum import Enum, auto
from uuid import uuid4

from mewcode.permissions import (
    PermissionChallenge,
    PermissionController,
    PermissionDecision,
    PermissionOutcome,
    PermissionPreflight,
)
from mewcode.hooks import HookEvent, HookRuntime, make_event
from mewcode.matching import MatchSubjectKind
from mewcode.tools import (
    ToolCallRequest,
    ToolExecution,
    ToolRegistry,
    ToolResult,
    ToolSafety,
    ValidatedToolCall,
)

from .events import (
    AgentEvent,
    AgentPermissionDecision,
    AgentPermissionRequest,
    AgentProgress,
    AgentToolResult,
)
from .control import AgentControlOperation, AgentControlTool


class ToolScheduleStateError(RuntimeError):
    pass


class _State(Enum):
    NEW = auto()
    RUNNING = auto()
    COMPLETE = auto()
    FAILED = auto()


PreparedCall = tuple[int, ValidatedToolCall, PermissionPreflight | None]


class ToolSchedule:
    def __init__(
        self,
        run_id: str,
        iteration: int,
        requests: Sequence[ToolCallRequest],
        registry: ToolRegistry,
        permission_controller: PermissionController,
        max_read_concurrency: int,
        prompt_id_factory: Callable[[], str],
        hook_runtime: HookRuntime | None = None,
    ) -> None:
        self._run_id = run_id
        self._iteration = iteration
        self._requests = tuple(requests)
        self._registry = registry
        self._permission_controller = permission_controller
        self._max_read_concurrency = max_read_concurrency
        self._prompt_id_factory = prompt_id_factory
        self._hook_runtime = hook_runtime
        self._state = _State.NEW
        self._executions: tuple[ToolExecution, ...] | None = None
        self._cancel_requested = asyncio.Event()
        self._active_tasks: set[asyncio.Task[ToolExecution]] = set()
        self._active_challenge: PermissionChallenge | None = None
        self._active_control: AgentControlOperation | None = None

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
                prepared: list[PreparedCall] = []
                for index, request in batch:
                    if self._cancel_requested.is_set():
                        execution = ToolExecution(index, request, _cancelled_result(request))
                        completed.append(execution)
                        yield self._result_event(execution)
                        continue

                    validated = self._registry.validate_call(request)
                    if isinstance(validated, ToolResult):
                        execution = ToolExecution(index, request, validated)
                        await self._dispatch_after(execution, "failure")
                        completed.append(execution)
                        yield self._result_event(execution)
                        continue

                    preflight, hard_decision = self._preflight(validated)
                    if hard_decision is not None:
                        yield self._decision_event(request, hard_decision)
                        execution = ToolExecution(
                            index,
                            request,
                            _permission_denied_result(request, hard_decision),
                        )
                        await self._dispatch_after(execution, "denied")
                        completed.append(execution)
                        yield self._result_event(execution)
                        continue

                    hook_denial = await self._dispatch_before(validated, preflight)
                    if hook_denial is not None:
                        execution = ToolExecution(
                            index, request, _hook_denied_result(request, hook_denial)
                        )
                        await self._dispatch_after(execution, "denied", preflight)
                        completed.append(execution)
                        yield self._result_event(execution)
                        continue

                    if isinstance(validated.tool, AgentControlTool):
                        operation = validated.tool.control_operation(request.arguments)
                        self._active_control = operation
                        try:
                            async for event in operation.events():
                                yield event
                            execution = ToolExecution(index, request, operation.result)
                        except asyncio.CancelledError:
                            self._cancel_requested.set()
                            await operation.cancel()
                            execution = ToolExecution(index, request, _cancelled_result(request))
                        finally:
                            if self._active_control is operation:
                                self._active_control = None
                        await self._dispatch_after(
                            execution,
                            "cancelled"
                            if execution.result.metadata.get("cancelled")
                            else ("success" if execution.result.ok else "failure"),
                            preflight,
                        )
                        completed.append(execution)
                        yield self._result_event(execution)
                        continue

                    decision = self._evaluate_preflight(validated, preflight)
                    if decision.outcome == PermissionOutcome.ASK:
                        assert decision.target is not None
                        challenge = PermissionChallenge(
                            prompt_id=self._prompt_id_factory(),
                            tool_call_id=request.id,
                            tool_name=request.name,
                            target=decision.target.value,
                        )
                        self._active_challenge = challenge
                        yield AgentPermissionRequest(
                            run_id=self._run_id,
                            iteration=self._iteration,
                            challenge=challenge,
                        )
                        try:
                            choice = await challenge.wait()
                        except asyncio.CancelledError:
                            self._cancel_requested.set()
                            execution = ToolExecution(
                                index, request, _cancelled_result(request)
                            )
                            await self._dispatch_after(
                                execution, "cancelled", preflight
                            )
                            completed.append(execution)
                            yield self._result_event(execution)
                            continue
                        finally:
                            if self._active_challenge is challenge:
                                self._active_challenge = None
                        decision = await self._permission_controller.apply_choice(
                            decision, choice
                        )

                    yield self._decision_event(request, decision)
                    if decision.outcome == PermissionOutcome.DENY:
                        execution = ToolExecution(
                            index, request, _permission_denied_result(request, decision)
                        )
                        await self._dispatch_after(execution, "denied", preflight)
                        completed.append(execution)
                        yield self._result_event(execution)
                    else:
                        prepared.append((index, validated, preflight))

                if prepared:
                    if self._is_read_batch(batch):
                        async for execution in self._run_read_batch(prepared):
                            completed.append(execution)
                            yield self._result_event(execution)
                    else:
                        index, validated, preflight = prepared[0]
                        execution = await self._run_serial(index, validated, preflight)
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
        challenge = self._active_challenge
        if challenge is not None:
            try:
                challenge.cancel()
            except RuntimeError:
                pass
        if self._active_control is not None:
            await self._active_control.cancel()
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
        self, batch: list[PreparedCall]
    ) -> AsyncIterator[ToolExecution]:
        semaphore = asyncio.Semaphore(self._max_read_concurrency)
        tasks = {
            asyncio.create_task(self._run_one(index, call, semaphore, preflight))
            for index, call, preflight in batch
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
        self,
        index: int,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> ToolExecution:
        task = asyncio.create_task(self._run_one(index, call, None, preflight))
        self._active_tasks.add(task)
        try:
            return await task
        finally:
            self._active_tasks.discard(task)

    async def _run_one(
        self,
        index: int,
        call: ValidatedToolCall,
        semaphore: asyncio.Semaphore | None,
        preflight: PermissionPreflight | None,
    ) -> ToolExecution:
        try:
            if self._cancel_requested.is_set():
                raise asyncio.CancelledError
            if semaphore is None:
                result = await self._registry.execute_validated(call)
            else:
                async with semaphore:
                    if self._cancel_requested.is_set():
                        raise asyncio.CancelledError
                    result = await self._registry.execute_validated(call)
        except asyncio.CancelledError:
            self._cancel_requested.set()
            result = _cancelled_result(call.request)
        execution = ToolExecution(index=index, request=call.request, result=result)
        await self._dispatch_after(
            execution,
            "cancelled"
            if result.metadata.get("cancelled")
            else ("success" if result.ok else "failure"),
            preflight,
        )
        return execution

    def _preflight(
        self, call: ValidatedToolCall
    ) -> tuple[PermissionPreflight | None, PermissionDecision | None]:
        method = getattr(self._permission_controller, "preflight", None)
        if method is None:
            return None, None
        result = method(call)
        if isinstance(result, PermissionDecision):
            return None, result
        return result, None

    def _evaluate_preflight(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> PermissionDecision:
        method = getattr(self._permission_controller, "evaluate_preflight", None)
        if preflight is not None and method is not None:
            return method(preflight)
        return self._permission_controller.evaluate(call)

    async def _dispatch_before(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> str | None:
        if self._hook_runtime is None:
            return None
        target = preflight.target if preflight is not None else None
        event = make_event(
            HookEvent.TOOL_BEFORE,
            workspace=self._hook_runtime.workspace,
            session_id=self._hook_runtime.session_id,
            resumed=self._hook_runtime.resumed,
            values={
                "tool": {
                    "call_id": call.request.id,
                    "name": call.request.name,
                    "arguments": call.request.arguments,
                    "target": {
                        "kind": target.kind.value if target is not None else None,
                        "value": target.value if target is not None else None,
                    },
                }
            },
            match_kinds={
                "tool.target.value": (
                    MatchSubjectKind.PATH
                    if target is not None
                    and target.kind.value in {"path", "path_glob"}
                    else MatchSubjectKind.TEXT
                )
            },
        )
        result = await self._hook_runtime.dispatch(event)
        if result.decision is not None and result.decision.deny:
            return result.decision.reason or "Hook denied this tool call."
        return None

    async def _dispatch_after(
        self,
        execution: ToolExecution,
        status: str,
        preflight: PermissionPreflight | None = None,
    ) -> None:
        if self._hook_runtime is None:
            return
        target = preflight.target if preflight is not None else None
        event = make_event(
            HookEvent.TOOL_AFTER,
            workspace=self._hook_runtime.workspace,
            session_id=self._hook_runtime.session_id,
            resumed=self._hook_runtime.resumed,
            values={
                "tool": {
                    "call_id": execution.request.id,
                    "name": execution.request.name,
                    "arguments": execution.request.arguments,
                    "target": {
                        "kind": target.kind.value if target is not None else None,
                        "value": target.value if target is not None else None,
                    },
                    "status": status,
                    "ok": execution.result.ok,
                    "result_summary": execution.result.summary(),
                    "error": (execution.result.error or "")[:4096],
                }
            },
        )
        await self._hook_runtime.dispatch(event)

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

    def _decision_event(
        self, request: ToolCallRequest, decision: PermissionDecision
    ) -> AgentPermissionDecision:
        return AgentPermissionDecision(
            run_id=self._run_id,
            iteration=self._iteration,
            tool_call_id=request.id,
            tool_name=request.name,
            target=decision.target.value if decision.target is not None else None,
            outcome=decision.outcome,
            source=decision.source,
            reason=decision.reason,
        )


class ToolScheduler:
    def __init__(
        self,
        permission_controller: PermissionController,
        max_read_concurrency: int = 4,
        prompt_id_factory: Callable[[], str] | None = None,
        hook_runtime: HookRuntime | None = None,
    ) -> None:
        if max_read_concurrency < 1:
            raise ValueError("max_read_concurrency must be at least 1")
        self._permission_controller = permission_controller
        self._max_read_concurrency = max_read_concurrency
        self._prompt_id_factory = prompt_id_factory or (lambda: str(uuid4()))
        self._hook_runtime = hook_runtime

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
            permission_controller=self._permission_controller,
            max_read_concurrency=self._max_read_concurrency,
            prompt_id_factory=self._prompt_id_factory,
            hook_runtime=self._hook_runtime,
        )


def _cancelled_result(request: ToolCallRequest) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=request.name,
        content="",
        error="Tool call cancelled.",
        metadata={"tool_call_id": request.id, "cancelled": True},
    )


def _permission_denied_result(
    request: ToolCallRequest, decision: PermissionDecision
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=request.name,
        content="",
        error=f"Permission denied ({decision.source.value}): {decision.reason}",
        metadata={
            "tool_call_id": request.id,
            "permission_denied": True,
            "permission_source": decision.source.value,
            "permission": {
                "outcome": decision.outcome.value,
                "source": decision.source.value,
            },
        },
    )


def _hook_denied_result(request: ToolCallRequest, reason: str) -> ToolResult:
    bounded = reason[:2048]
    return ToolResult(
        ok=False,
        tool_name=request.name,
        content="",
        error=f"Hook denied this tool call: {bounded}",
        metadata={
            "tool_call_id": request.id,
            "hook_denied": True,
            "hook_reason": bounded,
        },
    )
