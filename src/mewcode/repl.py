from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from typing import TextIO
from pathlib import Path

from .commands import (
    CommandDispatcher,
    CommandExecutionError,
    CommandRegistry,
    InputKind,
    InteractionMode,
    InteractionState,
    create_builtin_command_registry,
    parse_input,
)
from .context import ContextRuntimeStatus
from .continuity import MemoryRuntimeStatus, NullMemoryManager
from .agent import (
    AgentContinuityStatus,
    AgentContextStatus,
    AgentEvent,
    AgentPermissionDecision,
    AgentPermissionRequest,
    AgentProgress,
    AgentSubagentProgress,
    AgentStopped,
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    AgentToolResult,
)
from .conversation import Conversation, ConversationError, ConversationMode, ConversationStatus
from .permissions import PermissionChoice, PermissionController, PermissionMode
from .providers import UsageLedger, UsageSnapshot
from .terminal import RunControl, TerminalSession
from .hooks import HookRuntime, WorkspaceTrustStore

InputFunc = Callable[[str], str]


class Repl:
    def __init__(
        self,
        conversation: Conversation,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        input_func: InputFunc = input,
        permission_controller: PermissionController | None = None,
        startup_messages: tuple[str, ...] = (),
        *,
        registry: CommandRegistry | None = None,
        state: InteractionState | None = None,
        terminal: TerminalSession | None = None,
        usage_ledger: UsageLedger | None = None,
        memory_manager=None,
        context_manager=None,
        hook_runtime: HookRuntime | None = None,
        hook_trust_store: WorkspaceTrustStore | None = None,
        workspace: Path | None = None,
    ) -> None:
        self._conversation = conversation
        self._stdout = stdout
        self._stderr = stderr
        self._input = input_func
        self._permission_controller = permission_controller
        self._startup_messages = startup_messages
        self._registry = registry or create_builtin_command_registry()
        self._state = state or InteractionState()
        self._terminal = terminal or _LegacyTerminal(
            stdout, stderr, input_func
        )
        self._usage_ledger = usage_ledger or UsageLedger()
        self._memory_manager = memory_manager or NullMemoryManager()
        self._context_manager = context_manager
        self._hook_runtime = hook_runtime
        self._hook_trust_store = hook_trust_store
        self._workspace = workspace
        self._dispatcher = CommandDispatcher(self._registry, self, self)

    def run(self) -> int:
        with asyncio.Runner() as runner:
            try:
                return runner.run(self._run_loop())
            except KeyboardInterrupt:
                return 130

    async def _run_loop(self) -> int:
        self._terminal.write(
            "MewCode\nType /help for commands. Use /exit or /quit to exit.\n"
        )
        for message in self._startup_messages:
            self._terminal.write(f"{message}\n")
        if self._hook_runtime is not None and self._hook_runtime.trust_required:
            trusted = await self._prompt_hook_trust()
            persisted = (
                self._hook_trust_store.write(self._workspace, trusted)
                if self._hook_trust_store is not None and self._workspace is not None
                else False
            )
            self._hook_runtime.resolve_project_trust(trusted if persisted else False)
            if not persisted:
                self._terminal.write_error(
                    "Warning: Hook trust was not saved; project external Hooks remain disabled.\n"
                )
        start = getattr(self._conversation, "start", None)
        if start is not None:
            await start()
        monitor: asyncio.Task[None] | None = None
        has_subagents = getattr(self._conversation, "has_subagent_tasks", None)
        if has_subagents is not None and has_subagents():
            monitor = asyncio.create_task(self._monitor_subagent_tasks())
        try:
            while not self._state.exit_requested:
                try:
                    raw = await self._terminal.prompt()
                except EOFError:
                    self._terminal.write("\n")
                    return 0
                parsed = parse_input(raw)
                if parsed.kind is InputKind.EMPTY:
                    continue
                try:
                    refresh = getattr(self._conversation, "refresh_skills", None)
                    refreshed = refresh() if refresh is not None else None
                    if refreshed is not None:
                        for diagnostic in refreshed.diagnostics:
                            self._terminal.write_error(
                                f"Warning: {diagnostic.source}: {diagnostic.message}\n"
                            )
                    if parsed.kind is InputKind.COMMAND:
                        await self._dispatcher.dispatch(parsed)
                    else:
                        await self.send_user_message(parsed.text)
                except KeyboardInterrupt:
                    await self._conversation.cancel_active()
                    self._terminal.write("\nagent: cancelled\n")
                except ConversationError as exc:
                    self.show_error(exc.message)
                except asyncio.CancelledError:
                    await self._conversation.cancel_active()
                    self._terminal.write("\nagent: cancelled\n")
                except Exception:
                    await self._conversation.cancel_active()
                    self.show_error("event consumer failed.")
            return 0
        finally:
            try:
                warnings = await self._conversation.close()
                for warning in warnings:
                    self._terminal.write_error(f"Warning: {warning.message}\n")
            except Exception:
                self._terminal.write_error("Warning: conversation shutdown failed.\n")
            if monitor is not None:
                await asyncio.gather(monitor, return_exceptions=True)

    async def _monitor_subagent_tasks(self) -> None:
        try:
            async for event in self._conversation.subagent_terminal_events():
                summary = (
                    f"subagent[{event.task_id[:8]}]: {event.status.value}"
                )
                try:
                    await self._terminal.notify(summary)
                except Exception:
                    continue
        except Exception:
            return

    async def _prompt_hook_trust(self) -> bool:
        workspace = str(self._workspace or "workspace")
        source = str((self._workspace or Path.cwd()) / ".mewcode" / "hooks.yaml")
        prompt = getattr(self._terminal, "prompt_hook_trust", None)
        while True:
            try:
                if prompt is not None:
                    raw = (await prompt(workspace, source)).strip().lower()
                else:
                    raw = (
                        await self._terminal.prompt_permission(
                            f"trust project Hooks for {workspace}? [y]es/[n]o: "
                        )
                    ).strip().lower()
            except EOFError:
                return False
            if raw in {"y", "yes"}:
                return True
            if raw in {"n", "no"}:
                return False
            self._terminal.write_error("Choose y or n.\n")

    def show_message(self, message: str) -> None:
        self._terminal.write(f"{message}\n")

    def show_error(self, message: str) -> None:
        self._terminal.write_error(f"Error: {message}\n")

    def clear_display(self) -> None:
        self._terminal.clear()

    async def send_user_message(
        self, message: str, *, read_only: bool = False
    ) -> None:
        if read_only:
            mode = ConversationMode.READ_ONLY
        elif self._state.mode is InteractionMode.PLAN:
            mode = ConversationMode.PLAN
        else:
            mode = ConversationMode.DEFAULT
        source = self._conversation.send(message, mode)
        await self._consume(source)
        self._terminal.write("\n")

    def interaction_mode(self) -> InteractionMode:
        return self._state.mode

    def set_interaction_mode(self, mode: InteractionMode) -> None:
        self._state.mode = mode

    def token_usage(self) -> UsageSnapshot:
        return self._usage_ledger.snapshot()

    def refresh_status(self) -> None:
        self._terminal.invalidate()

    def request_exit(self) -> None:
        self._state.exit_requested = True

    async def compact_context(self) -> None:
        await self._consume(self._conversation.compact())
        self._terminal.write("\n")

    def session_status(self) -> ConversationStatus:
        return self._conversation.status()

    def memory_status(self) -> MemoryRuntimeStatus:
        return self._memory_manager.status()

    def context_status(self) -> ContextRuntimeStatus:
        if self._context_manager is None:
            return ContextRuntimeStatus(True, 0)
        return self._context_manager.status()

    def permission_mode(self) -> PermissionMode:
        if self._permission_controller is None:
            raise CommandExecutionError("Permission controller is unavailable.")
        return self._permission_controller.mode

    def set_permission_mode(self, mode: PermissionMode) -> None:
        if self._permission_controller is None:
            raise CommandExecutionError("Permission controller is unavailable.")
        self._permission_controller.set_mode(mode)

    async def invoke_skill(
        self, name: str, input_text: str, raw_command: str
    ) -> None:
        mode = (
            ConversationMode.PLAN
            if self._state.mode is InteractionMode.PLAN
            else ConversationMode.DEFAULT
        )
        await self._consume(
            self._conversation.invoke_skill(name, input_text, raw_command, mode)
        )
        self._terminal.write("\n")

    async def reset_conversation(self) -> None:
        await self._conversation.reset()

    def list_subagent_tasks(self):
        return self._conversation.list_subagent_tasks()

    def get_subagent_task(self, task_id: str):
        return self._conversation.get_subagent_task(task_id)

    async def cancel_subagent_task(self, task_id: str):
        return await self._conversation.cancel_subagent_task(task_id)

    async def _consume(self, source: AsyncIterator[AgentEvent]) -> None:
        renderer = _EventRenderer()
        iterator = source.__aiter__()
        event_task = asyncio.create_task(_next_agent_event(iterator))
        control_reader = getattr(self._terminal, "read_run_control", None)
        control_task = (
            asyncio.create_task(_next_run_control(control_reader))
            if control_reader is not None
            else None
        )
        try:
            while event_task is not None:
                waiters = {event_task}
                if control_task is not None:
                    waiters.add(control_task)
                done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                if event_task in done:
                    try:
                        has_event, value = event_task.result()
                    except Exception:
                        raise
                    if not has_event:
                        if isinstance(value, StopAsyncIteration):
                            return
                        raise value
                    event = value
                    event_task = None
                    if isinstance(event, AgentPermissionRequest):
                        if control_task is not None:
                            control_task.cancel()
                            await asyncio.gather(control_task, return_exceptions=True)
                            control_task = None
                        await self._handle_permission_request(event)
                        event_task = asyncio.create_task(_next_agent_event(iterator))
                        if control_reader is not None:
                            control_task = asyncio.create_task(
                                _next_run_control(control_reader)
                            )
                        continue
                    text = renderer.render(event)
                    if text is not None:
                        self._terminal.write(text)
                    event_task = asyncio.create_task(_next_agent_event(iterator))
                if control_task is not None and control_task in done:
                    has_control, value = control_task.result()
                    control_task = None
                    if not has_control:
                        raise value
                    control = value
                    if control is RunControl.BACKGROUND:
                        task_id = await self._conversation.background_foreground_subagent()
                        if task_id is None:
                            self._terminal.write("subagent: no foreground task to background\n")
                        else:
                            self._terminal.write(
                                f"subagent[{task_id[:8]}]: moved to background\n"
                            )
                    if control_reader is not None:
                        control_task = asyncio.create_task(
                            _next_run_control(control_reader)
                        )
        finally:
            pending = [
                task
                for task in (event_task, control_task)
                if task is not None and not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _handle_permission_request(self, event: AgentPermissionRequest) -> None:
        challenge = event.challenge
        prompt = (
            f"permission: allow {challenge.tool_name}({challenge.target})? "
            "[d]eny/[o]nce/[s]ession/[p]ermanent: "
        )
        choices = {
            "d": PermissionChoice.DENY,
            "deny": PermissionChoice.DENY,
            "o": PermissionChoice.ONCE,
            "once": PermissionChoice.ONCE,
            "s": PermissionChoice.SESSION,
            "session": PermissionChoice.SESSION,
            "p": PermissionChoice.PERMANENT,
            "permanent": PermissionChoice.PERMANENT,
        }
        while True:
            try:
                raw = (await self._terminal.prompt_permission(prompt)).strip().lower()
            except EOFError:
                challenge.resolve(PermissionChoice.DENY)
                self._terminal.write("\n")
                return
            choice = choices.get(raw)
            if choice is not None:
                challenge.resolve(choice)
                return
            self._terminal.write_error("Choose d, o, s, or p.\n")


class _LegacyTerminal:
    def __init__(
        self,
        stdout: TextIO,
        stderr: TextIO,
        input_func: InputFunc,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._input = input_func

    async def prompt(self) -> str:
        return self._input("mew> ")

    async def prompt_permission(self, message: str) -> str:
        return self._input(message)

    async def prompt_hook_trust(self, workspace: str, source: str) -> str:
        return self._input(
            f"trust project Hooks for {workspace} ({source})? [y]es/[n]o: "
        )

    async def read_run_control(self) -> RunControl:
        future = asyncio.get_running_loop().create_future()
        return await future

    async def notify(self, text: str) -> None:
        self.write(" ".join(text.splitlines())[:512] + "\n")

    def write(self, text: str) -> None:
        self._stdout.write(text)
        self._stdout.flush()

    def write_error(self, text: str) -> None:
        self._stderr.write(text)
        self._stderr.flush()

    def clear(self) -> None:
        self.write("\x1b[2J\x1b[H")

    def invalidate(self) -> None:
        return None


class _EventRenderer:
    def __init__(self) -> None:
        self._seen_iteration = False
        self._at_line_start = True

    def render(self, event: AgentEvent) -> str | None:
        text = _format_event(event)
        if text is None:
            return None

        if isinstance(event, AgentTextDelta):
            self._update_line_state(text)
            return text

        prefix = self._line_prefix(event)
        if _is_secondary_event(event):
            text = _indent_lines(text)
        rendered = prefix + text
        self._update_line_state(rendered)
        return rendered

    def _line_prefix(self, event: AgentEvent) -> str:
        is_iteration = (
            isinstance(event, AgentProgress)
            and event.phase == "iteration_started"
        )
        if is_iteration:
            if self._seen_iteration:
                prefix = "\n" if self._at_line_start else "\n\n"
            else:
                prefix = "" if self._at_line_start else "\n"
            self._seen_iteration = True
            return prefix
        return "" if self._at_line_start else "\n"

    def _update_line_state(self, text: str) -> None:
        if text:
            self._at_line_start = text.endswith("\n")


def _format_event(event: AgentEvent) -> str | None:
    if isinstance(event, AgentContinuityStatus):
        return f"{event.component}: {event.message}\n"
    if isinstance(event, AgentContextStatus):
        return f"context: {event.status.message}\n"
    if isinstance(event, AgentTextDelta):
        return event.text
    if isinstance(event, AgentSubagentProgress):
        message = " ".join(event.message.splitlines())[:160]
        return (
            f"subagent[{event.task_id[:8]}]: {event.status}"
            f" - {message}\n"
        )
    if isinstance(event, AgentToolCall):
        return f"tool: {event.request.name} ...\n"
    if isinstance(event, AgentToolResult):
        result = event.execution.result
        label = "ok" if result.ok else "failed"
        return f"tool: {event.execution.request.name} {label} - {result.summary()}\n"
    if isinstance(event, AgentPermissionDecision):
        target = f"({event.target})" if event.target is not None else ""
        return (
            f"permission: {event.tool_name}{target} {event.outcome.value} "
            f"[{event.source.value}] - {event.reason}\n"
        )
    if isinstance(event, AgentTokenUsage):
        current = event.current
        cumulative = event.cumulative
        return (
            "tokens: "
            f"in={_token(current.input_tokens)} "
            f"out={_token(current.output_tokens)} "
            f"total={_token(current.total_tokens)} "
            f"cache-read={_token(current.cache_read_tokens)} "
            f"cache-write={_token(current.cache_write_tokens)} "
            f"cumulative={_token(cumulative.total_tokens)} "
            f"cumulative-cache-read={_token(cumulative.cache_read_tokens)} "
            f"cumulative-cache-write={_token(cumulative.cache_write_tokens)}\n"
        )
    if isinstance(event, AgentProgress):
        if event.phase == "iteration_started":
            return f"agent: iteration {event.iteration}\n"
        if event.phase == "tool_batch_started":
            return f"agent: {event.message}\n"
        return None
    if isinstance(event, AgentStopped):
        if event.reason.value == "completed":
            return "agent: completed\n"
        detail = f" - {event.error}" if event.error else ""
        return f"agent: stopped ({event.reason.value}){detail}\n"
    return None


def _token(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _is_secondary_event(event: AgentEvent) -> bool:
    return isinstance(
        event,
        (
            AgentPermissionDecision,
            AgentContinuityStatus,
            AgentContextStatus,
            AgentToolCall,
            AgentToolResult,
            AgentTokenUsage,
        ),
    ) or (
        isinstance(event, AgentProgress)
        and event.phase == "tool_batch_started"
    )


def _indent_lines(text: str) -> str:
    return "".join(f"  {line}" for line in text.splitlines(keepends=True))


async def _next_agent_event(iterator):
    try:
        return True, await anext(iterator)
    except BaseException as exc:
        return False, exc


async def _next_run_control(reader):
    try:
        return True, await reader()
    except BaseException as exc:
        return False, exc
