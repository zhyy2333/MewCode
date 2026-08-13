from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Protocol, TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, CompleteEvent, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import DummyHistory
from prompt_toolkit.input import Input, create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import Output, create_output
from prompt_toolkit.output.plain_text import PlainTextOutput
from prompt_toolkit.shortcuts import CompleteStyle

from .commands import CommandRegistry, InteractionState


class TerminalSession(Protocol):
    async def prompt(self) -> str: ...

    async def prompt_permission(self, message: str) -> str: ...

    async def prompt_hook_trust(self, workspace: str, source: str) -> str: ...

    def write(self, text: str) -> None: ...

    def write_error(self, text: str) -> None: ...

    def clear(self) -> None: ...

    def invalidate(self) -> None: ...


class CommandCompleter(Completer):
    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        prefix = document.text_before_cursor
        if not prefix.startswith("/") or " " in prefix:
            return
        for candidate in self._registry.completion_candidates(prefix):
            yield Completion(candidate, start_position=-len(prefix))


def _apply_tab(
    buffer: Buffer,
    registry: CommandRegistry,
    completer: CommandCompleter,
) -> None:
    completions = list(
        completer.get_completions(
            buffer.document,
            CompleteEvent(completion_requested=True),
        )
    )
    if len(completions) == 1:
        completion = completions[0]
        buffer.apply_completion(completion)
        definition = registry.resolve(completion.text.removeprefix("/"))
        if definition is not None and definition.argument_hint:
            buffer.insert_text(" ")
    elif completions:
        buffer.start_completion(select_first=False)


def _key_bindings(
    registry: CommandRegistry,
    completer: CommandCompleter,
) -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("tab")
    def complete(event) -> None:
        _apply_tab(event.current_buffer, registry, completer)

    return bindings


class PromptToolkitTerminal:
    def __init__(
        self,
        registry: CommandRegistry,
        state: InteractionState,
        *,
        stdin: Input | None = None,
        output: Output | None = None,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
    ) -> None:
        self._state = state
        self._stdout = stdout
        self._stderr = stderr
        self._input = stdin or create_input()
        if output is not None:
            self._output = output
        else:
            try:
                self._output = create_output(stdout=stdout)
            except Exception:
                # prompt_toolkit's Windows output probes the console even for
                # redirected streams. Keep non-interactive invocations usable.
                self._output = PlainTextOutput(stdout)
        self._completer = CommandCompleter(registry)
        self._session: PromptSession[str] = PromptSession(
            message="mew> ",
            completer=self._completer,
            complete_while_typing=False,
            complete_style=CompleteStyle.MULTI_COLUMN,
            history=DummyHistory(),
            key_bindings=_key_bindings(registry, self._completer),
            bottom_toolbar=self._bottom_toolbar,
            input=self._input,
            output=self._output,
        )
        self._permission_session: PromptSession[str] = PromptSession(
            history=DummyHistory(),
            input=self._input,
            output=self._output,
        )

    def _bottom_toolbar(self) -> str:
        return f"[{self._state.mode.value.upper()}]"

    async def prompt(self) -> str:
        return await self._session.prompt_async()

    async def prompt_permission(self, message: str) -> str:
        return await self._permission_session.prompt_async(message)

    async def prompt_hook_trust(self, workspace: str, source: str) -> str:
        return await self._permission_session.prompt_async(
            f"trust project Hooks for {workspace} ({source})? [y]es/[n]o: "
        )

    def write(self, text: str) -> None:
        self._stdout.write(text)
        self._stdout.flush()

    def write_error(self, text: str) -> None:
        self._stderr.write(text)
        self._stderr.flush()

    def clear(self) -> None:
        self._output.erase_screen()
        self._output.cursor_goto(0, 0)
        self._output.flush()

    def invalidate(self) -> None:
        application = get_app_or_none()
        if application is not None and application.is_running:
            application.invalidate()
