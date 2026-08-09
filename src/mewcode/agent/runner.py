from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable
from uuid import uuid4

from mewcode.providers import (
    DEFAULT_MAX_TOKENS,
    ChatMessage,
    LLMProvider,
    ProviderError,
    ProviderFinishReason,
    TokenUsage,
)
from mewcode.tools import ToolRegistry

from .events import (
    AgentEvent,
    AgentMode,
    AgentProgress,
    AgentStopped,
    StopReason,
)
from .scheduler import ToolSchedule, ToolScheduler
from .streaming import StreamCollector

PLAN_FINAL_MAX_TOKENS = 8192
PLAN_FINAL_PROMPT = """Using the workspace evidence gathered above, output the complete implementation plan now.
Do not call tools. Return only the final plan, with concrete steps and verification."""


class AgentRunStateError(RuntimeError):
    pass


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
    ) -> None:
        self._run_id = run_id
        self._mode = mode
        self._provider = provider
        self._scheduler = scheduler
        self._config = config
        self._history = list(history)
        self._user_message = ChatMessage(role="user", content=user_text)
        self._tools = tools
        self._state = _State.NEW
        self._outcome: AgentRunOutcome | None = None
        self._cancel_requested = asyncio.Event()
        self._done = asyncio.Event()
        self._consumer_task: asyncio.Task[object] | None = None
        self._active_schedule: ToolSchedule | None = None

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._state is not _State.NEW:
            raise AgentRunStateError("An agent run can only be consumed once.")
        self._state = _State.RUNNING
        self._consumer_task = asyncio.current_task()
        working_messages = self._history + [self._user_message]
        new_messages: list[ChatMessage] = []
        user_committed = False
        cumulative_usage = TokenUsage.zero()
        consecutive_unknown = 0
        iteration = 0
        final_text = ""
        plan_finalizing = False

        try:
            yield AgentProgress(
                run_id=self._run_id,
                iteration=0,
                phase="run_started",
                message=f"{self._mode.value} run started",
            )
            tool_definitions = self._provider.tool_definitions(self._tools)

            loop_limit = (
                self._config.plan_max_investigation_iterations + 1
                if self._mode is AgentMode.PLAN
                else self._config.max_iterations
            )
            for iteration in range(1, loop_limit + 1):
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
                    request_tools = None if plan_finalizing else tool_definitions
                    max_output_tokens = (
                        self._config.plan_final_max_tokens
                        if plan_finalizing
                        else DEFAULT_MAX_TOKENS
                    )
                    source = self._provider.stream_reply(
                        list(working_messages),
                        tools=request_tools,
                        max_output_tokens=max_output_tokens,
                    )
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
                        if not user_committed:
                            new_messages.append(self._user_message)
                            user_committed = True
                        new_messages.extend(assistant_messages)
                        working_messages.extend(assistant_messages)
                        final_prompt = ChatMessage(role="user", content=PLAN_FINAL_PROMPT)
                        new_messages.append(final_prompt)
                        working_messages.append(final_prompt)
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
                    self._tools.get(request.name) is None
                    for request in response.tool_calls
                )
                consecutive_unknown = consecutive_unknown + 1 if all_unknown else 0

                schedule = self._scheduler.schedule(
                    self._run_id,
                    iteration,
                    response.tool_calls,
                    self._tools,
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
                assistant_messages = self._provider.assistant_messages(response)
                tool_messages = self._provider.tool_result_messages(executions)
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
                    final_prompt = ChatMessage(role="user", content=PLAN_FINAL_PROMPT)
                    new_messages.append(final_prompt)
                    working_messages.append(final_prompt)
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
        except Exception as exc:
            yield self._finish(
                StopReason.ERROR,
                iteration,
                final_text,
                new_messages,
                cumulative_usage,
                f"Unexpected agent error: {exc}",
            )
        finally:
            self._consumer_task = None
            self._done.set()

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
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._provider = provider
        self._scheduler = scheduler
        self._config = config
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def start(
        self,
        history: Sequence[ChatMessage],
        user_text: str,
        tools: ToolRegistry,
        mode: AgentMode = AgentMode.DIRECT,
    ) -> AgentRun:
        return AgentRun(
            run_id=self._id_factory(),
            mode=mode,
            provider=self._provider,
            scheduler=self._scheduler,
            config=self._config,
            history=history,
            user_text=user_text,
            tools=tools,
        )
