from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from typing import TextIO

from .agent import (
    AgentContinuityStatus,
    AgentContextStatus,
    AgentEvent,
    AgentPermissionDecision,
    AgentPermissionRequest,
    AgentProgress,
    AgentStopped,
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    AgentToolResult,
)
from .conversation import Conversation, ConversationError
from .permissions import PermissionChoice, PermissionController, PermissionMode

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
    ) -> None:
        self._conversation = conversation
        self._stdout = stdout
        self._stderr = stderr
        self._input = input_func
        self._permission_controller = permission_controller
        self._startup_messages = startup_messages

    def run(self) -> int:
        self._stdout.write("MewCode\n")
        self._stdout.write(
            "Type /exit or /quit to exit. Use /plan <task>, /do, /compact, or "
            "/permissions.\n"
        )
        for message in self._startup_messages:
            self._stdout.write(f"{message}\n")
        self._stdout.flush()

        with asyncio.Runner() as runner:
            try:
                while True:
                    try:
                        user_text = self._input("mew> ").strip()
                    except EOFError:
                        self._stdout.write("\n")
                        self._stdout.flush()
                        return 0
                    if not user_text:
                        continue
                    if user_text in {"/exit", "/quit"}:
                        return 0
                    if self._handle_permissions_command(user_text):
                        continue

                    try:
                        source = self._route(user_text)
                        runner.run(self._consume(source))
                        self._stdout.write("\n")
                        self._stdout.flush()
                    except KeyboardInterrupt:
                        runner.run(self._conversation.cancel_active())
                        self._stdout.write("\nagent: cancelled\n")
                        self._stdout.flush()
                    except ConversationError as exc:
                        self._stderr.write(f"Error: {exc.message}\n")
                        self._stderr.flush()
                    except Exception as exc:
                        runner.run(self._conversation.cancel_active())
                        self._stderr.write(f"Error: event consumer failed: {exc}\n")
                        self._stderr.flush()
            finally:
                try:
                    warnings = runner.run(self._conversation.close())
                    for warning in warnings:
                        self._stderr.write(f"Warning: {warning.message}\n")
                    self._stderr.flush()
                except Exception:
                    self._stderr.write("Warning: conversation shutdown failed.\n")
                    self._stderr.flush()

    def _route(self, user_text: str) -> AsyncIterator[AgentEvent]:
        if user_text == "/plan":
            return self._conversation.plan("")
        if user_text.startswith("/plan "):
            return self._conversation.plan(user_text[len("/plan ") :])
        if user_text == "/do":
            return self._conversation.execute_plan()
        if user_text == "/compact":
            return self._conversation.compact()
        if user_text.startswith("/compact "):
            raise ConversationError("Usage: /compact")
        return self._conversation.ask(user_text)

    async def _consume(self, source: AsyncIterator[AgentEvent]) -> None:
        renderer = _EventRenderer()
        async for event in source:
            if isinstance(event, AgentPermissionRequest):
                self._handle_permission_request(event)
                continue
            text = renderer.render(event)
            if text is None:
                continue
            self._stdout.write(text)
            self._stdout.flush()

    def _handle_permissions_command(self, user_text: str) -> bool:
        if user_text != "/permissions" and not user_text.startswith("/permissions "):
            return False
        if self._permission_controller is None:
            self._stderr.write("Error: permission controller is unavailable.\n")
            self._stderr.flush()
            return True
        parts = user_text.split()
        if len(parts) == 1:
            self._stdout.write(
                f"permission mode: {self._permission_controller.mode.value}\n"
            )
            self._stdout.flush()
            return True
        if len(parts) != 2:
            self._write_permissions_usage()
            return True
        try:
            mode = PermissionMode(parts[1])
        except ValueError:
            self._write_permissions_usage()
            return True
        self._permission_controller.set_mode(mode)
        self._stdout.write(f"permission mode: {mode.value}\n")
        self._stdout.flush()
        return True

    def _write_permissions_usage(self) -> None:
        self._stderr.write("Usage: /permissions [strict|default|allow]\n")
        self._stderr.flush()

    def _handle_permission_request(self, event: AgentPermissionRequest) -> None:
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
                raw = self._input(prompt).strip().lower()
            except EOFError:
                challenge.resolve(PermissionChoice.DENY)
                self._stdout.write("\n")
                self._stdout.flush()
                return
            choice = choices.get(raw)
            if choice is not None:
                challenge.resolve(choice)
                return
            self._stderr.write("Choose d, o, s, or p.\n")
            self._stderr.flush()


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
