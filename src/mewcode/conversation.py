from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from .prompting import PromptAdditions, PromptRunContext
from .agent import (
    AgentContextStatus,
    AgentEvent,
    AgentMode,
    AgentRun,
    AgentRunOutcome,
    AgentRunStateError,
    AgentRunner,
)
from .context import ContextManager, ContextOperation, ContextStatus
from .continuity import SessionBinding, SessionState, StoredPlan
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
        context_manager: ContextManager | None = None,
        *,
        initial_state: SessionState | None = None,
        session: SessionBinding | None = None,
    ) -> None:
        self._runner = runner
        self._tools = tools
        self._prompt_additions = prompt_additions
        self._context_manager = context_manager
        self._session = session
        self._messages = list(initial_state.messages) if initial_state is not None else []
        stored_plan = initial_state.pending_plan if initial_state is not None else None
        self._pending_plan = (
            PendingPlan(stored_plan.task, stored_plan.text)
            if stored_plan is not None
            else None
        )
        self._active_run: AgentRun | None = None
        self._last_outcome: AgentRunOutcome | None = None
        self._active_context_operation: ContextOperation | None = None

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
            pending = PendingPlan(clean_task, outcome.final_text)
            if self._session is not None:
                try:
                    self._session.commit_plan(StoredPlan(pending.task, pending.text))
                except Exception as exc:
                    raise ConversationError(
                        "The pending plan could not be persisted."
                    ) from exc
            self._pending_plan = pending

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
            if self._session is not None:
                try:
                    self._session.commit_plan(None)
                except Exception as exc:
                    raise ConversationError(
                        "The pending plan could not be cleared."
                    ) from exc
            self._pending_plan = None

    async def cancel_active(self) -> None:
        if self._active_run is not None:
            await self._active_run.cancel()
        if self._active_context_operation is not None:
            await self._active_context_operation.cancel()

    async def compact(self) -> AsyncIterator[AgentEvent]:
        if self._context_manager is None:
            raise ConversationError("Context management is unavailable.")
        if self._active_run is not None or self._active_context_operation is not None:
            raise ConversationError("Another conversation operation is already active.")
        operation = self._context_manager.compact(self._messages)
        self._active_context_operation = operation
        try:
            async for status in operation.statuses():
                yield AgentContextStatus("compact", 0, status)
            outcome = operation.outcome
            if outcome.changed:
                if self._session is not None:
                    try:
                        self._session.commit_history(outcome.messages)
                    except Exception as exc:
                        raise ConversationError(
                            "The compacted session could not be persisted."
                        ) from exc
                self._messages = list(outcome.messages)
        finally:
            if self._active_context_operation is operation:
                self._active_context_operation = None

    async def close(self) -> tuple[ContextStatus, ...]:
        await self.cancel_active()
        if self._session is not None:
            self._session.close()
        if self._context_manager is None:
            return ()
        return self._context_manager.close()

    async def _run(
        self,
        user_text: str,
        tools: ToolRegistry,
        mode: AgentMode,
        prompt_context: PromptRunContext,
    ) -> AsyncIterator[AgentEvent]:
        if self._active_run is not None or self._active_context_operation is not None:
            raise ConversationError("Another conversation operation is already active.")
        run = self._runner.start(
            self._messages,
            user_text,
            tools,
            mode,
            prompt_context,
            history_commit_sink=self._session,
        )
        self._active_run = run
        self._last_outcome = None
        try:
            async for event in run.events():
                yield event
            self._last_outcome = run.outcome
            self._messages = list(run.outcome.committed_history)
        except AgentRunStateError as exc:
            raise ConversationError(str(exc)) from exc
        finally:
            if self._active_run is run:
                self._active_run = None
