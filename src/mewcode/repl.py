from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from typing import TextIO

from .agent import (
    AgentEvent,
    AgentProgress,
    AgentStopped,
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    AgentToolResult,
)
from .conversation import Conversation, ConversationError

InputFunc = Callable[[str], str]


class Repl:
    def __init__(
        self,
        conversation: Conversation,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        input_func: InputFunc = input,
    ) -> None:
        self._conversation = conversation
        self._stdout = stdout
        self._stderr = stderr
        self._input = input_func

    def run(self) -> int:
        self._stdout.write("MewCode\n")
        self._stdout.write(
            "Type /exit or /quit to exit. Use /plan <task> then /do for Plan Mode.\n"
        )
        self._stdout.flush()

        with asyncio.Runner() as runner:
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

                source = self._route(user_text)
                try:
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

    def _route(self, user_text: str) -> AsyncIterator[AgentEvent]:
        if user_text == "/plan":
            return self._conversation.plan("")
        if user_text.startswith("/plan "):
            return self._conversation.plan(user_text[len("/plan ") :])
        if user_text == "/do":
            return self._conversation.execute_plan()
        return self._conversation.ask(user_text)

    async def _consume(self, source: AsyncIterator[AgentEvent]) -> None:
        renderer = _EventRenderer()
        async for event in source:
            text = renderer.render(event)
            if text is None:
                continue
            self._stdout.write(text)
            self._stdout.flush()


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
    if isinstance(event, AgentTextDelta):
        return event.text
    if isinstance(event, AgentToolCall):
        return f"tool: {event.request.name} ...\n"
    if isinstance(event, AgentToolResult):
        result = event.execution.result
        label = "ok" if result.ok else "failed"
        return f"tool: {event.execution.request.name} {label} - {result.summary()}\n"
    if isinstance(event, AgentTokenUsage):
        current = event.current
        cumulative = event.cumulative
        return (
            "tokens: "
            f"in={_token(current.input_tokens)} "
            f"out={_token(current.output_tokens)} "
            f"total={_token(current.total_tokens)} "
            f"cumulative={_token(cumulative.total_tokens)}\n"
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
        event, (AgentToolCall, AgentToolResult, AgentTokenUsage)
    ) or (
        isinstance(event, AgentProgress)
        and event.phase == "tool_batch_started"
    )


def _indent_lines(text: str) -> str:
    return "".join(f"  {line}" for line in text.splitlines(keepends=True))
