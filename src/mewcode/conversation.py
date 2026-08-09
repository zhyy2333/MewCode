from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from .prompting import PromptAdditions, PromptRunContext
from .agent import (
    AgentEvent,
    AgentMode,
    AgentRun,
    AgentRunOutcome,
    AgentRunStateError,
    AgentRunner,
)
from .providers import ChatMessage
from .tools import ToolRegistry, ToolSafety


class ConversationError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class PendingPlan:
    task: str
    text: str


class Conversation:
    def __init__(
        self,
        runner: AgentRunner,
        tools: ToolRegistry,
        prompt_additions: PromptAdditions = PromptAdditions(),
    ) -> None:
        self._runner = runner
        self._tools = tools
        self._prompt_additions = prompt_additions
        self._messages: list[ChatMessage] = []
        self._pending_plan: PendingPlan | None = None
        self._active_run: AgentRun | None = None
        self._last_outcome: AgentRunOutcome | None = None

    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    def pending_plan(self) -> PendingPlan | None:
        return self._pending_plan

    async def ask(self, user_text: str) -> AsyncIterator[AgentEvent]:
        text = user_text.strip()
        if not text:
            raise ConversationError("Message must not be empty.")
        context = PromptRunContext(task=text, additions=self._prompt_additions)
        async for event in self._run(
            text, self._tools, AgentMode.DIRECT, context
        ):
            yield event

    async def plan(self, task: str) -> AsyncIterator[AgentEvent]:
        clean_task = task.strip()
        if not clean_task:
            raise ConversationError("Usage: /plan <task>")
        readonly = self._tools.select({ToolSafety.READ_ONLY})
        context = PromptRunContext(
            task=clean_task,
            additions=self._prompt_additions,
        )
        async for event in self._run(clean_task, readonly, AgentMode.PLAN, context):
            yield event
        outcome = self._last_outcome
        if (
            outcome is not None
            and outcome.completed
            and outcome.final_text.strip()
        ):
            self._pending_plan = PendingPlan(clean_task, outcome.final_text)

    async def execute_plan(self) -> AsyncIterator[AgentEvent]:
        plan = self._pending_plan
        if plan is None:
            raise ConversationError("No pending plan. Use /plan <task> first.")
        context = PromptRunContext(
            task=plan.task,
            approved_plan=plan.text,
            additions=self._prompt_additions,
        )
        async for event in self._run("/do", self._tools, AgentMode.EXECUTE, context):
            yield event
        outcome = self._last_outcome
        if outcome is not None and outcome.completed:
            self._pending_plan = None

    async def cancel_active(self) -> None:
        if self._active_run is not None:
            await self._active_run.cancel()

    async def _run(
        self,
        user_text: str,
        tools: ToolRegistry,
        mode: AgentMode,
        prompt_context: PromptRunContext,
    ) -> AsyncIterator[AgentEvent]:
        if self._active_run is not None:
            raise ConversationError("Another agent run is already active.")
        run = self._runner.start(
            self._messages,
            user_text,
            tools,
            mode,
            prompt_context,
        )
        self._active_run = run
        self._last_outcome = None
        try:
            async for event in run.events():
                yield event
            self._last_outcome = run.outcome
            self._messages.extend(run.outcome.new_messages)
        except AgentRunStateError as exc:
            raise ConversationError(str(exc)) from exc
        finally:
            if self._active_run is run:
                self._active_run = None
