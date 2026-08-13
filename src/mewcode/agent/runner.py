from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

from mewcode.context import (
    ContextArchiveError,
    ContextFailureKind,
    ContextManager,
)
from mewcode.hooks import HookRuntime
from mewcode.prompting import (
    PromptAdditions,
    PromptBuilder,
    PromptEnvironmentProvider,
    PromptPhase,
    PromptRunContext,
)
from mewcode.providers import (
    CaptureOnlyRequestBoundary,
    DEFAULT_MAX_TOKENS,
    ChatMessage,
    LLMProvider,
    ModelRequest,
    ProviderError,
    ProviderFinishReason,
    TokenUsage,
    ProviderRequestBoundary,
    RequestSnapshotSlot,
    bind_request_boundary,
)
from mewcode.permissions import PermissionMode
from mewcode.tools import ToolRegistry, ToolSafety

from .events import (
    AgentContextStatus,
    AgentEvent,
    AgentMode,
    AgentProgress,
    AgentStopped,
    StopReason,
)
from .scheduler import ToolSchedule, ToolScheduler
from .streaming import StreamCollector
from .control import AgentControlContext, ForkRequestSeed

PLAN_FINAL_MAX_TOKENS = 8192


class AgentRunStateError(RuntimeError):
    pass


class HistoryCommitSink(Protocol):
    def commit(self, messages: Sequence[ChatMessage]) -> None: ...


class _HistoryCommitError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRunView:
    tools: ToolRegistry
    additions: PromptAdditions | None = None


RunViewProvider = Callable[[], AgentRunView]
RequestBoundaryFactory = Callable[[RequestSnapshotSlot], ProviderRequestBoundary]


@dataclass(frozen=True)
class AgentRunConfig:
    max_iterations: int = 20
    unknown_tool_limit: int = 3
    plan_max_investigation_iterations: int = 6
    plan_final_max_tokens: int = PLAN_FINAL_MAX_TOKENS

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if self.unknown_tool_limit < 1:
            raise ValueError("unknown_tool_limit must be at least 1")
        if self.plan_max_investigation_iterations < 1:
            raise ValueError("plan_max_investigation_iterations must be at least 1")
        if self.plan_final_max_tokens < 1:
            raise ValueError("plan_final_max_tokens must be at least 1")


@dataclass(frozen=True)
class AgentRunOutcome:
    run_id: str
    mode: AgentMode
    reason: StopReason
    final_text: str
    new_messages: tuple[ChatMessage, ...]
    committed_history: tuple[ChatMessage, ...]
    usage: TokenUsage
    error: str | None = None

    @property
    def completed(self) -> bool:
        return self.reason is StopReason.COMPLETED


class _State(Enum):
    NEW = auto()
    RUNNING = auto()
    COMPLETE = auto()


class AgentRun:
    def __init__(
        self,
        *,
        run_id: str,
        mode: AgentMode,
        provider: LLMProvider,
        scheduler: ToolScheduler,
        config: AgentRunConfig,
        history: Sequence[ChatMessage],
        user_text: str,
        tools: ToolRegistry,
        prompt_builder: PromptBuilder,
        prompt_context: PromptRunContext,
        context_manager: ContextManager | None,
        history_commit_sink: HistoryCommitSink | None,
        run_view_provider: RunViewProvider | None = None,
        hook_runtime: HookRuntime | None = None,
        profile_name: str = "default",
        permission_mode_supplier: Callable[[], PermissionMode] | None = None,
        allowed_safety: frozenset[ToolSafety] = frozenset(
            {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
        ),
        seed_request: ForkRequestSeed | None = None,
        request_boundary_factory: RequestBoundaryFactory | None = None,
    ) -> None:
        self._run_id = run_id
        self._mode = mode
        self._provider = provider
        self._scheduler = scheduler
        self._config = config
        self._history = list(history)
        self._user_message = ChatMessage(role="user", content=user_text)
        self._tools = tools
        self._prompt_builder = prompt_builder
        self._prompt_context = prompt_context
        self._context_manager = context_manager
        self._history_commit_sink = history_commit_sink
        self._run_view_provider = run_view_provider
        self._hook_runtime = hook_runtime
        self._profile_name = profile_name
        self._permission_mode_supplier = permission_mode_supplier or (
            lambda: PermissionMode.DEFAULT
        )
        self._allowed_safety = allowed_safety
        self._seed_request = seed_request
        self._request_boundary_factory = request_boundary_factory or (
            lambda slot: CaptureOnlyRequestBoundary(slot)
        )
        self._state = _State.NEW
        self._outcome: AgentRunOutcome | None = None
        self._cancel_requested = asyncio.Event()
        self._done = asyncio.Event()
        self._consumer_task: asyncio.Task[object] | None = None
        self._active_schedule: ToolSchedule | None = None
        self._committed_history = tuple(history)

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._state is not _State.NEW:
            raise AgentRunStateError("An agent run can only be consumed once.")
        self._state = _State.RUNNING
        self._consumer_task = asyncio.current_task()
        working_messages = (
            list(self._seed_request.request.messages) + [self._user_message]
            if self._seed_request is not None
            else self._history + [self._user_message]
        )
        new_messages: list[ChatMessage] = []
        user_committed = False
        cumulative_usage = TokenUsage.zero()
        consecutive_unknown = 0
        iteration = 0
        final_text = ""
        plan_finalizing = False
        plan_investigation_messages: list[ChatMessage] = []
        scope = (
            self._hook_runtime.bind_scope(
                run_id=self._run_id,
                mode=self._mode.value,
                component="agent",
            )
            if self._hook_runtime is not None
            else None
        )
        if scope is not None:
            scope.__enter__()

        try:
            yield AgentProgress(
                run_id=self._run_id,
                iteration=0,
                phase="run_started",
                message=f"{self._mode.value} run started",
            )
            loop_limit = (
                self._seed_request.max_iterations
                if self._seed_request is not None
                else (
                    self._config.plan_max_investigation_iterations + 1
                    if self._mode is AgentMode.PLAN
                    else self._config.max_iterations
                )
            )
            for iteration in range(1, loop_limit + 1):
                if self._hook_runtime is not None:
                    self._hook_runtime.update_scope(iteration=iteration)
                if self._cancel_requested.is_set():
                    yield self._finish(
                        StopReason.CANCELLED,
                        iteration - 1,
                        final_text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                yield AgentProgress(
                    run_id=self._run_id,
                    iteration=iteration,
                    phase="iteration_started",
                    message=f"iteration {iteration}",
                )
                collector = StreamCollector(self._run_id, iteration)
                try:
                    iteration_tools = self._tools
                    iteration_context = self._prompt_context
                    if self._run_view_provider is not None:
                        view = self._run_view_provider()
                        iteration_tools = view.tools
                        if view.additions is not None:
                            iteration_context = replace(
                                iteration_context,
                                additions=iteration_context.additions.merged(
                                    custom_instructions=getattr(view.additions, "custom_instructions", None),
                                    agent_role=getattr(view.additions, "agent_role", None),
                                    available_skills=getattr(view.additions, "available_skills", None),
                                    active_skills=getattr(view.additions, "active_skills", None),
                                    long_term_memory=getattr(view.additions, "long_term_memory", None),
                                ),
                            )
                    request_tools = None if plan_finalizing else iteration_tools
                    if self._seed_request is not None and iteration == 1:
                        request_tools = self._seed_request.request.tools
                    max_output_tokens = (
                        self._config.plan_final_max_tokens
                        if plan_finalizing
                        else DEFAULT_MAX_TOKENS
                    )
                    phase = (
                        PromptPhase.PLAN_FINALIZATION
                        if plan_finalizing
                        else PromptPhase.ACTIVE
                    )
                    prompt = (
                        self._seed_request.request.prompt
                        if self._seed_request is not None
                        else self._prompt_builder.build(
                            iteration_context,
                            self._mode.value,
                            phase,
                            iteration,
                        )
                    )
                    model_request = ModelRequest(
                        prompt=prompt,
                        messages=tuple(working_messages),
                        tools=request_tools,
                        max_output_tokens=(
                            self._seed_request.request.max_output_tokens
                            if self._seed_request is not None and iteration == 1
                            else max_output_tokens
                        ),
                    )
                    request_footprint = None
                    if self._context_manager is not None:
                        operation = self._context_manager.prepare(
                            model_request,
                            preserve_prefix=(
                                self._seed_request is not None and iteration == 1
                            ),
                        )
                        async for status in operation.statuses():
                            yield AgentContextStatus(
                                self._run_id,
                                iteration,
                                status,
                            )
                        preparation = operation.outcome
                        cumulative_usage = cumulative_usage.add(preparation.usage)
                        if preparation.changed:
                            working_messages = list(preparation.messages)
                            candidate = tuple(
                                [
                                    *(
                                        message
                                        for message in preparation.messages
                                        if user_committed
                                        or message is not self._user_message
                                    ),
                                    *plan_investigation_messages,
                                ]
                            )
                            self._commit_history(candidate)
                        if preparation.request is None:
                            reason = (
                                StopReason.CONTEXT_CAPACITY
                                if preparation.failure_kind
                                is ContextFailureKind.CAPACITY
                                else StopReason.CONTEXT_COMPACTION
                            )
                            yield self._finish(
                                reason,
                                iteration,
                                final_text,
                                new_messages,
                                cumulative_usage,
                                preparation.error,
                            )
                            return
                        model_request = preparation.request
                        request_footprint = preparation.footprint
                    snapshot_slot = RequestSnapshotSlot()
                    boundary = self._request_boundary_factory(snapshot_slot)
                    with bind_request_boundary(boundary):
                        source = self._provider.stream_reply(model_request)
                        async for event in collector.events(source, cumulative_usage):
                            yield event
                except asyncio.CancelledError:
                    self._cancel_requested.set()
                    yield self._finish(
                        StopReason.CANCELLED,
                        iteration,
                        final_text,
                        new_messages,
                        cumulative_usage,
                    )
                    return
                except ProviderError as exc:
                    yield self._finish(
                        StopReason.STREAM_ERROR,
                        iteration,
                        final_text,
                        new_messages,
                        cumulative_usage,
                        exc.message,
                    )
                    return

                response = collector.response
                if self._context_manager is not None:
                    self._context_manager.observe_usage(
                        request_footprint,
                        response.usage,
                    )
                cumulative_usage = cumulative_usage.add(response.usage)
                final_text = response.text
                yield AgentProgress(
                    run_id=self._run_id,
                    iteration=iteration,
                    phase="model_completed",
                    message="model response completed",
                )

                if response.finish_reason is ProviderFinishReason.OUTPUT_LIMIT:
                    yield self._finish(
                        StopReason.OUTPUT_LIMIT,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                if plan_finalizing:
                    if response.finish_reason is ProviderFinishReason.TOOL_CALLS:
                        raise AgentRunStateError(
                            "Plan finalization returned a tool call while tools were disabled."
                        )
                    if response.finish_reason is not ProviderFinishReason.NATURAL:
                        raise AgentRunStateError(
                            f"Unsupported provider finish reason: {response.finish_reason}"
                        )
                    if not response.text.strip():
                        yield self._finish(
                            StopReason.EMPTY_RESPONSE,
                            iteration,
                            response.text,
                            new_messages,
                            cumulative_usage,
                        )
                        return
                    assistant_messages = self._provider.assistant_messages(response)
                    candidate = tuple(
                        [
                            *working_messages,
                            *plan_investigation_messages,
                            *assistant_messages,
                        ]
                    )
                    self._commit_history(candidate)
                    if not user_committed:
                        new_messages.append(self._user_message)
                        user_committed = True
                    new_messages.extend(assistant_messages)
                    yield self._finish(
                        StopReason.COMPLETED,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                if response.finish_reason is ProviderFinishReason.NATURAL:
                    if self._mode is AgentMode.PLAN:
                        assistant_messages = self._provider.assistant_messages(response)
                        candidate = tuple(
                            [*working_messages, *plan_investigation_messages, *assistant_messages]
                        )
                        self._commit_history(candidate)
                        if not user_committed:
                            new_messages.append(self._user_message)
                            user_committed = True
                        new_messages.extend(assistant_messages)
                        plan_investigation_messages.extend(assistant_messages)
                        plan_finalizing = True
                        continue
                    if not response.text.strip():
                        yield self._finish(
                            StopReason.EMPTY_RESPONSE,
                            iteration,
                            response.text,
                            new_messages,
                            cumulative_usage,
                        )
                        return
                    assistant_messages = self._provider.assistant_messages(response)
                    candidate = tuple([*working_messages, *assistant_messages])
                    self._commit_history(candidate)
                    if not user_committed:
                        new_messages.append(self._user_message)
                        user_committed = True
                    new_messages.extend(assistant_messages)
                    working_messages.extend(assistant_messages)
                    yield self._finish(
                        StopReason.COMPLETED,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                if response.finish_reason is not ProviderFinishReason.TOOL_CALLS:
                    raise AgentRunStateError(
                        f"Unsupported provider finish reason: {response.finish_reason}"
                    )

                if (
                    self._mode is not AgentMode.PLAN
                    and iteration == self._config.max_iterations
                ):
                    yield self._finish(
                        StopReason.ITERATION_LIMIT,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                all_unknown = all(
                    iteration_tools.get(request.name) is None
                    for request in response.tool_calls
                )
                consecutive_unknown = consecutive_unknown + 1 if all_unknown else 0

                parent_request = snapshot_slot.request
                control_context = (
                    AgentControlContext(
                        run_id=self._run_id,
                        iteration=iteration,
                        mode=self._mode,
                        profile_name=self._profile_name,
                        permission_mode=self._permission_mode_supplier(),
                        max_iterations=loop_limit,
                        allowed_safety=self._allowed_safety,
                        parent_request=parent_request,
                    )
                    if parent_request is not None
                    else None
                )
                schedule = self._scheduler.schedule(
                    self._run_id,
                    iteration,
                    response.tool_calls,
                    iteration_tools,
                    control_context,
                )
                self._active_schedule = schedule
                try:
                    async for event in schedule.events():
                        yield event
                except asyncio.CancelledError:
                    self._cancel_requested.set()
                    await schedule.cancel()
                    yield self._finish(
                        StopReason.CANCELLED,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return
                finally:
                    self._active_schedule = None

                executions = schedule.executions
                if schedule.cancelled:
                    self._cancel_requested.set()
                group_id = f"{self._run_id}:{iteration}"
                if self._context_manager is not None:
                    try:
                        tool_compaction = self._context_manager.compact_tool_results(
                            executions
                        )
                    except ContextArchiveError:
                        yield self._finish(
                            StopReason.CONTEXT_COMPACTION,
                            iteration,
                            response.text,
                            new_messages,
                            cumulative_usage,
                            "A tool result could not be archived safely.",
                        )
                        return
                    executions = tool_compaction.executions
                    for status in tool_compaction.statuses:
                        yield AgentContextStatus(self._run_id, iteration, status)
                assistant_messages = self._provider.assistant_messages(
                    response,
                    group_id,
                )
                tool_messages = self._provider.tool_result_messages(
                    executions,
                    group_id,
                )
                candidate = tuple(
                    [*working_messages, *assistant_messages, *tool_messages]
                )
                self._commit_history(candidate)
                if not user_committed:
                    new_messages.append(self._user_message)
                    user_committed = True
                new_messages.extend(assistant_messages)
                new_messages.extend(tool_messages)
                working_messages.extend(assistant_messages)
                working_messages.extend(tool_messages)

                if self._cancel_requested.is_set():
                    yield self._finish(
                        StopReason.CANCELLED,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                if consecutive_unknown >= self._config.unknown_tool_limit:
                    yield self._finish(
                        StopReason.UNKNOWN_TOOL_LIMIT,
                        iteration,
                        response.text,
                        new_messages,
                        cumulative_usage,
                    )
                    return

                if (
                    self._mode is AgentMode.PLAN
                    and iteration
                    == self._config.plan_max_investigation_iterations
                ):
                    plan_finalizing = True

            raise AgentRunStateError("Agent loop ended without a stop reason.")
        except asyncio.CancelledError:
            self._cancel_requested.set()
            if self._active_schedule is not None:
                await self._active_schedule.cancel()
            yield self._finish(
                StopReason.CANCELLED,
                iteration,
                final_text,
                new_messages,
                cumulative_usage,
            )
        except _HistoryCommitError as exc:
            yield self._finish(
                StopReason.SESSION_PERSISTENCE,
                iteration,
                final_text,
                new_messages,
                cumulative_usage,
                str(exc),
            )
        except Exception as exc:
            if self._hook_runtime is not None:
                await self._hook_runtime.system_error("agent", exc)
            yield self._finish(
                StopReason.ERROR,
                iteration,
                final_text,
                new_messages,
                cumulative_usage,
                f"Unexpected agent error: {exc}",
            )
        finally:
            if scope is not None:
                scope.__exit__(None, None, None)
            self._consumer_task = None
            self._done.set()

    def _commit_history(self, messages: Sequence[ChatMessage]) -> None:
        candidate = tuple(messages)
        try:
            if self._history_commit_sink is not None:
                self._history_commit_sink.commit(candidate)
        except Exception as exc:
            raise _HistoryCommitError(
                "The current session could not be persisted."
            ) from exc
        self._committed_history = candidate

    async def cancel(self) -> None:
        if self._state is _State.COMPLETE:
            return
        self._cancel_requested.set()
        if self._active_schedule is not None:
            await self._active_schedule.cancel()
        elif self._consumer_task is not None and self._consumer_task is not asyncio.current_task():
            self._consumer_task.cancel()
        if self._state is _State.RUNNING and self._consumer_task is not asyncio.current_task():
            await self._done.wait()

    @property
    def outcome(self) -> AgentRunOutcome:
        if self._state is not _State.COMPLETE or self._outcome is None:
            raise AgentRunStateError("The agent run has not completed.")
        return self._outcome

    def _finish(
        self,
        reason: StopReason,
        iteration: int,
        final_text: str,
        new_messages: Sequence[ChatMessage],
        usage: TokenUsage,
        error: str | None = None,
    ) -> AgentStopped:
        if self._outcome is not None:
            raise AgentRunStateError("The agent run already has an outcome.")
        self._outcome = AgentRunOutcome(
            run_id=self._run_id,
            mode=self._mode,
            reason=reason,
            final_text=final_text,
            new_messages=tuple(new_messages),
            committed_history=self._committed_history,
            usage=usage,
            error=error,
        )
        self._state = _State.COMPLETE
        return AgentStopped(
            run_id=self._run_id,
            iteration=iteration,
            reason=reason,
            final_text=final_text,
            usage=usage,
            error=error,
        )


class AgentRunner:
    def __init__(
        self,
        provider: LLMProvider,
        scheduler: ToolScheduler,
        config: AgentRunConfig = AgentRunConfig(),
        *,
        prompt_builder: PromptBuilder | None = None,
        id_factory: Callable[[], str] | None = None,
        context_manager: ContextManager | None = None,
        hook_runtime: HookRuntime | None = None,
        profile_name: str = "default",
        permission_mode_supplier: Callable[[], PermissionMode] | None = None,
        allowed_safety: frozenset[ToolSafety] = frozenset(
            {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
        ),
        request_boundary_factory: RequestBoundaryFactory | None = None,
    ) -> None:
        self._provider = provider
        self._scheduler = scheduler
        self._config = config
        self._prompt_builder = prompt_builder or PromptBuilder(
            PromptEnvironmentProvider(Path.cwd())
        )
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._context_manager = context_manager
        self._hook_runtime = hook_runtime
        self._profile_name = profile_name
        self._permission_mode_supplier = permission_mode_supplier or (
            lambda: PermissionMode.DEFAULT
        )
        self._allowed_safety = allowed_safety
        self._request_boundary_factory = request_boundary_factory

    def start(
        self,
        history: Sequence[ChatMessage],
        user_text: str,
        tools: ToolRegistry,
        mode: AgentMode = AgentMode.DIRECT,
        prompt_context: PromptRunContext | None = None,
        history_commit_sink: HistoryCommitSink | None = None,
        run_view_provider: RunViewProvider | None = None,
        seed_request: ForkRequestSeed | None = None,
        allowed_safety: frozenset[ToolSafety] | None = None,
    ) -> AgentRun:
        if seed_request is not None:
            if not user_text.strip():
                raise ValueError("A fork task must not be empty.")
            if seed_request.profile_name != self._profile_name:
                raise ValueError(
                    "The fork request profile does not match this AgentRunner."
                )
            if allowed_safety is None:
                allowed_safety = seed_request.allowed_safety
        return AgentRun(
            run_id=self._id_factory(),
            mode=mode,
            provider=self._provider,
            scheduler=self._scheduler,
            config=self._config,
            history=history,
            user_text=user_text,
            tools=tools,
            prompt_builder=self._prompt_builder,
            prompt_context=prompt_context or PromptRunContext(task=user_text),
            context_manager=self._context_manager,
            history_commit_sink=history_commit_sink,
            run_view_provider=run_view_provider,
            hook_runtime=self._hook_runtime,
            profile_name=self._profile_name,
            permission_mode_supplier=self._permission_mode_supplier,
            allowed_safety=(
                self._allowed_safety if allowed_safety is None else allowed_safety
            ),
            seed_request=seed_request,
            request_boundary_factory=self._request_boundary_factory,
        )
