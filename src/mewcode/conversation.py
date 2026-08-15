from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from .prompting import PromptAdditions, PromptRunContext
from .agent import (
    AgentContinuityStatus,
    AgentContextStatus,
    AgentEvent,
    AgentMode,
    AgentRun,
    AgentRunOutcome,
    AgentRunStateError,
    AgentRunner,
)
from .context import ContextManager, ContextOperation, ContextStatus
from .continuity import (
    ContinuityDiagnostic,
    InstructionSnapshot,
    MemoryManager,
    MemoryTurn,
    MemoryScope,
    NullMemoryManager,
    SessionBinding,
    SessionState,
    StoredPlan,
)
from .continuity.session_codec import session_title
from .providers import ChatMessage
from .hooks import HookEvent, HookRuntime, make_event
from .tools import ToolRegistry, ToolSafety
from .skills import SkillCoordinator, SkillMode, SkillRefreshResult, SkillRuntime
from .subagents import (
    RootAgentRequestBoundary,
    SubagentDiagnostic,
    SubagentTaskManager,
    SubagentTaskSnapshot,
    SubagentTerminalEvent,
    TaskCancelResult,
)
from .worktrees import (
    WorktreeDeleteResult,
    WorktreeJanitor,
    WorktreeLifecycleService,
    WorktreePathPolicy,
    WorktreeStatus,
)


class ConversationError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class PendingPlan:
    task: str
    text: str


class ConversationMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    READ_ONLY = "read_only"


@dataclass(frozen=True)
class ConversationStatus:
    session_id: str
    title: str
    resumed: bool
    message_count: int
    busy: bool


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
        instructions: InstructionSnapshot = InstructionSnapshot(),
        memory: MemoryManager | NullMemoryManager | None = None,
        resumed: bool = False,
        skill_runtime: SkillRuntime | None = None,
        skill_coordinator: SkillCoordinator | None = None,
        skill_refresher: Callable[[], SkillRefreshResult] | None = None,
        hook_runtime: HookRuntime | None = None,
        task_manager: SubagentTaskManager | None = None,
        worktree_lifecycle: WorktreeLifecycleService | None = None,
        worktree_janitor: WorktreeJanitor | None = None,
    ) -> None:
        self._runner = runner
        self._tools = tools
        self._prompt_additions = prompt_additions
        self._context_manager = context_manager
        self._session = session
        self._instructions = instructions
        self._memory = memory or NullMemoryManager()
        self._session_id = (
            initial_state.session_id if initial_state is not None else "ephemeral"
        )
        self._resumed = resumed
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
        self._skill_runtime = skill_runtime
        self._skill_coordinator = skill_coordinator
        self._skill_refresher = skill_refresher
        self._active_skill_safety = {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
        self._hook_runtime = hook_runtime
        self._task_manager = task_manager
        self._worktree_lifecycle = worktree_lifecycle
        self._worktree_janitor = worktree_janitor
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started or self._closed:
            return
        self._started = True
        if self._worktree_janitor is not None:
            await self._worktree_janitor.start()
        if self._hook_runtime is not None:
            await self._hook_runtime.dispatch(
                make_event(
                    HookEvent.SESSION_START,
                    workspace=self._hook_runtime.workspace,
                    session_id=self._session_id,
                    resumed=self._resumed,
                )
            )

    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    def pending_plan(self) -> PendingPlan | None:
        return self._pending_plan

    def status(self) -> ConversationStatus:
        return ConversationStatus(
            session_id=self._session_id,
            title=session_title(self._messages, self._session_id),
            resumed=self._resumed,
            message_count=len(self._messages),
            busy=(
                self._active_run is not None
                or self._active_context_operation is not None
            ),
        )

    async def send(
        self,
        user_text: str,
        mode: ConversationMode = ConversationMode.DEFAULT,
    ) -> AsyncIterator[AgentEvent]:
        text = user_text.strip()
        if not text:
            raise ConversationError("Message must not be empty.")
        async for event in self._preflight():
            yield event
        tools = (
            self._tools
            if mode is ConversationMode.DEFAULT
            else self._tools.select({ToolSafety.READ_ONLY})
        )
        agent_mode = AgentMode.PLAN if mode is ConversationMode.PLAN else AgentMode.DIRECT
        allowed_safety = (
            {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
            if mode is ConversationMode.DEFAULT
            else {ToolSafety.READ_ONLY}
        )
        self._active_skill_safety = allowed_safety
        context = PromptRunContext(task=text, additions=self._current_additions())
        view_provider = (
            (lambda: self._skill_runtime.run_view(allowed_safety))
            if self._skill_runtime is not None
            else None
        )
        async for event in self._run(
            text, tools, agent_mode, context, run_view_provider=view_provider
        ):
            yield event

    def set_skill_coordinator(self, coordinator: SkillCoordinator) -> None:
        self._skill_coordinator = coordinator

    def current_skill_safety(self) -> set[ToolSafety]:
        return set(self._active_skill_safety)

    def skill_base_additions(self) -> PromptAdditions:
        return self._current_additions()

    def subagent_user_additions(self) -> PromptAdditions:
        return self._prompt_additions.merged(
            custom_instructions=self._instructions.user_content,
            long_term_memory=self._memory.scope_prompt_view(MemoryScope.USER).content,
        )

    def refresh_skills(self) -> SkillRefreshResult | None:
        return self._skill_refresher() if self._skill_refresher is not None else None

    async def invoke_skill(
        self,
        name: str,
        input_text: str,
        raw_command: str,
        mode: ConversationMode = ConversationMode.DEFAULT,
    ) -> AsyncIterator[AgentEvent]:
        if self._skill_coordinator is None or self._skill_runtime is None:
            raise ConversationError("Skill execution is unavailable.")
        async for event in self._preflight():
            yield event
        definition = self._skill_runtime.catalog.get(name)
        if definition is None:
            raise ConversationError(f"Unknown Skill: {name}")
        self._active_skill_safety = (
            {ToolSafety.READ_ONLY, ToolSafety.SIDE_EFFECT}
            if mode is ConversationMode.DEFAULT
            else {ToolSafety.READ_ONLY}
        )
        operation = self._skill_coordinator.invoke(name, input_text)
        async for event in operation.events():
            yield event
        result = operation.result
        if not result.ok:
            raise ConversationError(result.error or f"Skill '{name}' failed.")
        if definition.mode is SkillMode.SHARED:
            context = PromptRunContext(
                task=input_text or f"Run Skill '{name}'.",
                additions=self._current_additions(),
            )
            async for event in self._run(
                raw_command,
                self._tools,
                AgentMode.PLAN if mode is ConversationMode.PLAN else AgentMode.DIRECT,
                context,
                run_view_provider=lambda: self._skill_runtime.run_view(
                    self._active_skill_safety
                ),
            ):
                yield event
            return
        candidate = (
            *self._messages,
            ChatMessage("user", raw_command),
            ChatMessage("assistant", result.content),
        )
        try:
            if self._session is not None:
                self._session.commit_history(candidate)
        except Exception as exc:
            raise ConversationError("The isolated Skill result could not be persisted.") from exc
        self._messages = list(candidate)
        self._memory.schedule(
            MemoryTurn(
                self._session_id,
                raw_command,
                result.content,
                self._session.now() if self._session is not None else datetime.now().astimezone(),
            )
        )

    async def reset(self) -> None:
        if self._active_run is not None or self._active_context_operation is not None:
            raise ConversationError("Another conversation operation is already active.")
        if self._task_manager is not None:
            try:
                await self._task_manager.reset()
            except Exception as exc:
                raise ConversationError("Subagent tasks could not be reset.") from exc
        await self._memory.await_pending()
        try:
            if self._session is not None:
                self._session.reset_state()
        except Exception as exc:
            raise ConversationError("The current conversation could not be reset.") from exc
        self._messages = []
        self._pending_plan = None
        if self._skill_runtime is not None:
            self._skill_runtime.reset(persist=False)
        if self._context_manager is not None:
            self._context_manager.reset_runtime_state()

    async def ask(self, user_text: str) -> AsyncIterator[AgentEvent]:
        async for event in self.send(user_text, ConversationMode.DEFAULT):
            yield event

    async def plan(self, task: str) -> AsyncIterator[AgentEvent]:
        clean_task = task.strip()
        if not clean_task:
            raise ConversationError("Usage: /plan <task>")
        async for event in self._preflight():
            yield event
        readonly = self._tools.select({ToolSafety.READ_ONLY})
        context = PromptRunContext(
            task=clean_task,
            additions=self._current_additions(),
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
        async for event in self._preflight():
            yield event
        context = PromptRunContext(
            task=plan.task,
            approved_plan=plan.text,
            additions=self._current_additions(),
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

    def has_subagent_tasks(self) -> bool:
        return self._task_manager is not None

    def list_subagent_tasks(self) -> tuple[SubagentTaskSnapshot, ...]:
        return self._task_manager.list() if self._task_manager is not None else ()

    def get_subagent_task(self, task_id: str) -> SubagentTaskSnapshot | None:
        return self._task_manager.get(task_id) if self._task_manager is not None else None

    async def cancel_subagent_task(self, task_id: str) -> TaskCancelResult:
        if self._task_manager is None:
            return TaskCancelResult.NOT_FOUND
        try:
            return await self._task_manager.cancel(task_id)
        except Exception as exc:
            raise ConversationError("The subagent task could not be cancelled.") from exc

    async def list_worktrees(self) -> tuple[WorktreeStatus, ...]:
        if self._worktree_lifecycle is None:
            return ()
        try:
            return await self._worktree_lifecycle.list_managed()
        except Exception as exc:
            raise ConversationError("Managed Worktrees could not be listed.") from exc

    async def delete_worktree(self, name: str, *, force: bool) -> WorktreeDeleteResult:
        if self._worktree_lifecycle is None:
            raise ConversationError("Worktree isolation is unavailable.")
        try:
            parsed = WorktreePathPolicy().parse_name(name)
            return await self._worktree_lifecycle.delete(parsed, force=force)
        except Exception as exc:
            raise ConversationError("Managed Worktree deletion was rejected.") from exc

    async def background_foreground_subagent(self) -> str | None:
        if self._task_manager is None:
            return None
        try:
            return await self._task_manager.detach_current_foreground("manual")
        except Exception as exc:
            raise ConversationError("The foreground subagent could not be backgrounded.") from exc

    async def subagent_terminal_events(self) -> AsyncIterator[SubagentTerminalEvent]:
        if self._task_manager is None:
            return
        async for event in self._task_manager.terminal_events():
            yield event

    async def compact(self) -> AsyncIterator[AgentEvent]:
        if self._context_manager is None:
            raise ConversationError("Context management is unavailable.")
        if self._active_run is not None or self._active_context_operation is not None:
            raise ConversationError("Another conversation operation is already active.")
        async for event in self._preflight():
            yield event
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

    async def close(self) -> tuple[ContextStatus | ContinuityDiagnostic | SubagentDiagnostic, ...]:
        if self._closed:
            return ()
        self._closed = True
        await self.cancel_active()
        diagnostics: list[ContextStatus | ContinuityDiagnostic | SubagentDiagnostic] = []
        if self._task_manager is not None:
            try:
                diagnostics.extend(await self._task_manager.close())
            except Exception:
                diagnostics.append(
                    SubagentDiagnostic(None, "Subagent task shutdown did not finish cleanly.")
                )
        if self._worktree_janitor is not None:
            try:
                await self._worktree_janitor.close()
            except Exception:
                diagnostics.append(
                    SubagentDiagnostic(None, "Worktree cleanup shutdown did not finish cleanly.")
                )
        try:
            diagnostics.extend(await self._memory.close())
        except Exception:
            diagnostics.append(
                SubagentDiagnostic(None, "Memory shutdown did not finish cleanly.")
            )
        if self._hook_runtime is not None and self._started:
            await self._hook_runtime.dispatch(
                make_event(
                    HookEvent.SESSION_END,
                    workspace=self._hook_runtime.workspace,
                    session_id=self._session_id,
                    resumed=self._resumed,
                    values={"session": {"id": self._session_id, "resumed": self._resumed, "status": "success"}},
                )
            )
        if self._session is not None:
            try:
                diagnostics.extend(self._session.close())
            except Exception:
                diagnostics.append(
                    SubagentDiagnostic(None, "Session shutdown did not finish cleanly.")
                )
        if self._skill_runtime is not None:
            try:
                self._skill_runtime.close()
            except Exception:
                diagnostics.append(
                    SubagentDiagnostic(None, "Skill shutdown did not finish cleanly.")
                )
        if self._context_manager is not None:
            try:
                diagnostics.extend(self._context_manager.close())
            except Exception:
                diagnostics.append(
                    SubagentDiagnostic(None, "Context shutdown did not finish cleanly.")
                )
        if self._hook_runtime is not None:
            try:
                await self._hook_runtime.close()
            except Exception:
                diagnostics.append(
                    SubagentDiagnostic(None, "Hook shutdown did not finish cleanly.")
                )
        return tuple(diagnostics)

    async def _run(
        self,
        user_text: str,
        tools: ToolRegistry,
        mode: AgentMode,
        prompt_context: PromptRunContext,
        run_view_provider=None,
    ) -> AsyncIterator[AgentEvent]:
        if self._active_run is not None or self._active_context_operation is not None:
            raise ConversationError("Another conversation operation is already active.")
        turn_id = uuid4().hex
        scope = None
        if self._hook_runtime is not None:
            await self._hook_runtime.dispatch(
                make_event(
                    HookEvent.TURN_START,
                    workspace=self._hook_runtime.workspace,
                    session_id=self._session_id,
                    resumed=self._resumed,
                    values={"turn": {"id": turn_id, "mode": mode.value, "input_summary": user_text[:4096]}},
                )
            )
            scope = self._hook_runtime.bind_scope(turn_id=turn_id, mode=mode.value)
            scope.__enter__()
        run = self._runner.start(
            self._messages,
            user_text,
            tools,
            mode,
            prompt_context,
            history_commit_sink=self._session,
            run_view_provider=run_view_provider,
            request_boundary_factory=(
                (
                    lambda slot: RootAgentRequestBoundary(
                        self._task_manager.notifications,
                        slot,
                    )
                )
                if self._task_manager is not None
                else None
            ),
        )
        self._active_run = run
        self._last_outcome = None
        turn_status = "failure"
        try:
            async for event in run.events():
                yield event
            self._last_outcome = run.outcome
            self._messages = list(run.outcome.committed_history)
            turn_status = (
                "success"
                if run.outcome.completed
                else "cancelled"
                if run.outcome.reason.value == "cancelled"
                else "failure"
            )
            if self._hook_runtime is not None:
                await self._hook_runtime.dispatch(
                    make_event(
                        HookEvent.TURN_END,
                        workspace=self._hook_runtime.workspace,
                        session_id=self._session_id,
                        resumed=self._resumed,
                        values={"turn": {"id": turn_id, "mode": mode.value, "input_summary": user_text[:4096], "status": turn_status}},
                    )
                )
            if run.outcome.completed:
                self._memory.schedule(
                    MemoryTurn(
                        self._session_id,
                        prompt_context.task,
                        run.outcome.final_text,
                        self._session.now()
                        if self._session is not None
                        else datetime.now().astimezone(),
                    )
                )
        except AgentRunStateError as exc:
            if self._hook_runtime is not None:
                await self._hook_runtime.dispatch(
                    make_event(
                        HookEvent.TURN_END,
                        workspace=self._hook_runtime.workspace,
                        session_id=self._session_id,
                        resumed=self._resumed,
                        values={"turn": {"id": turn_id, "mode": mode.value, "input_summary": user_text[:4096], "status": "failure"}},
                    )
                )
            raise ConversationError(str(exc)) from exc
        finally:
            if scope is not None:
                scope.__exit__(None, None, None)
            if self._active_run is run:
                self._active_run = None

    async def _preflight(self) -> AsyncIterator[AgentEvent]:
        diagnostics = list(await self._memory.await_pending())
        if self._session is not None:
            diagnostics.extend(self._session.maintain())
        for diagnostic in diagnostics:
            yield AgentContinuityStatus(
                "continuity",
                0,
                diagnostic.component.value,
                diagnostic.message,
                diagnostic.severity.value != "info",
            )

    def _current_additions(self) -> PromptAdditions:
        return self._prompt_additions.merged(
            custom_instructions=self._instructions.content,
            long_term_memory=self._memory.prompt_view().content,
        )
