from __future__ import annotations

import asyncio

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.input import create_pipe_input

from mewcode.commands import (
    InteractionMode,
    InteractionState,
    create_builtin_command_registry,
)
from mewcode.terminal import CommandCompleter, PromptToolkitTerminal, _apply_tab


def completion_texts(text: str, cursor: int | None = None) -> list[str]:
    completer = CommandCompleter(create_builtin_command_registry())
    document = Document(text, cursor_position=len(text) if cursor is None else cursor)
    return [
        item.text
        for item in completer.get_completions(
            document, CompleteEvent(completion_requested=True)
        )
    ]


def test_completer_is_case_insensitive_registry_driven_and_hidden_safe() -> None:
    assert completion_texts("/COMP") == ["/compact"]
    assert completion_texts("/p") == ["/permission", "/permissions", "/plan"]
    assert completion_texts("/q") == []
    assert completion_texts("hello") == []
    assert completion_texts("/help status") == []


def test_single_tab_applies_completion_and_argument_space() -> None:
    registry = create_builtin_command_registry()
    completer = CommandCompleter(registry)
    buffer = Buffer(completer=completer)
    buffer.text = "/comp"
    buffer.cursor_position = len(buffer.text)
    _apply_tab(buffer, registry, completer)
    assert buffer.text == "/compact"
    buffer.text = "/hel"
    buffer.cursor_position = len(buffer.text)
    _apply_tab(buffer, registry, completer)
    assert buffer.text == "/help "


def test_multiple_tab_starts_menu_without_selecting() -> None:
    async def scenario():
        registry = create_builtin_command_registry()
        completer = CommandCompleter(registry)
        buffer = Buffer(completer=completer)
        buffer.text = "/p"
        buffer.cursor_position = len(buffer.text)
        _apply_tab(buffer, registry, completer)
        await asyncio.sleep(0)
        return buffer

    buffer = asyncio.run(scenario())
    assert buffer.text == "/p"
    assert buffer.complete_state is not None
    assert len(buffer.complete_state.completions) == 3
    assert buffer.complete_state.complete_index is None


def test_toolbar_reads_shared_state_and_clear_is_supported() -> None:
    state = InteractionState()
    terminal = PromptToolkitTerminal(
        create_builtin_command_registry(), state, output=DummyOutput()
    )
    assert terminal._bottom_toolbar() == "[DEFAULT]"
    state.mode = InteractionMode.PLAN
    assert terminal._bottom_toolbar() == "[PLAN]"
    terminal.clear()
    terminal.invalidate()


def test_argument_area_and_permission_prompt_do_not_enable_command_completion() -> None:
    assert completion_texts("/help status") == []
    terminal = PromptToolkitTerminal(
        create_builtin_command_registry(), InteractionState(), output=DummyOutput()
    )
    assert terminal._permission_session.completer is None


def test_real_tab_key_sequence_completes_single_match() -> None:
    async def scenario() -> str:
        with create_pipe_input() as pipe:
            terminal = PromptToolkitTerminal(
                create_builtin_command_registry(),
                InteractionState(),
                stdin=pipe,
                output=DummyOutput(),
            )
            pipe.send_text("/comp\t\r")
            return await terminal.prompt()

    assert asyncio.run(scenario()) == "/compact"


def test_terminal_and_permission_prompts_propagate_eof() -> None:
    async def scenario(permission: bool) -> None:
        with create_pipe_input() as pipe:
            terminal = PromptToolkitTerminal(
                create_builtin_command_registry(),
                InteractionState(),
                stdin=pipe,
                output=DummyOutput(),
            )
            if permission:
                task = asyncio.create_task(
                    terminal.prompt_permission("permission: ")
                )
            else:
                task = asyncio.create_task(terminal.prompt())
            await asyncio.sleep(0)
            pipe.close()
            await task

    for permission in (False, True):
        try:
            asyncio.run(scenario(permission))
        except EOFError:
            pass
        else:
            raise AssertionError("EOF must propagate from prompt_toolkit")
