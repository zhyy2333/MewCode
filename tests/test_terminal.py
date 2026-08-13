from __future__ import annotations

import asyncio
import io
import pytest

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
from mewcode.terminal import (
    CommandCompleter,
    PromptToolkitTerminal,
    RunControl,
    _apply_tab,
)


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


def test_run_control_ignores_regular_keys_and_recognizes_ctrl_b() -> None:
    async def scenario():
        with create_pipe_input() as pipe:
            terminal = PromptToolkitTerminal(
                create_builtin_command_registry(),
                InteractionState(),
                stdin=pipe,
                output=DummyOutput(),
            )
            reader = asyncio.create_task(terminal.read_run_control())
            await asyncio.sleep(0)
            pipe.send_text("abc")
            await asyncio.sleep(0)
            assert not reader.done()
            pipe.send_bytes(b"\x02")
            return await reader

    assert asyncio.run(scenario()) is RunControl.BACKGROUND


def test_run_control_cancellation_releases_input_for_relisten() -> None:
    async def scenario():
        with create_pipe_input() as pipe:
            terminal = PromptToolkitTerminal(
                create_builtin_command_registry(),
                InteractionState(),
                stdin=pipe,
                output=DummyOutput(),
            )
            first = asyncio.create_task(terminal.read_run_control())
            await asyncio.sleep(0)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            second = asyncio.create_task(terminal.read_run_control())
            await asyncio.sleep(0)
            pipe.send_bytes(b"\x02")
            return await second

    assert asyncio.run(scenario()) is RunControl.BACKGROUND


def test_run_control_ctrl_c_preserves_keyboard_interrupt() -> None:
    async def scenario():
        with create_pipe_input() as pipe:
            terminal = PromptToolkitTerminal(
                create_builtin_command_registry(),
                InteractionState(),
                stdin=pipe,
                output=DummyOutput(),
            )
            reader = asyncio.create_task(terminal.read_run_control())
            await asyncio.sleep(0)
            pipe.send_bytes(b"\x03")
            await reader

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(scenario())


def test_notify_is_single_line_bounded_and_flushes_redirected_output() -> None:
    class Stream(io.StringIO):
        def __init__(self):
            super().__init__()
            self.flushes = 0

        def flush(self):
            self.flushes += 1

    stream = Stream()
    terminal = PromptToolkitTerminal(
        create_builtin_command_registry(),
        InteractionState(),
        output=DummyOutput(),
        stdout=stream,
    )
    asyncio.run(terminal.notify("first\nsecond" + "x" * 600))
    assert stream.getvalue().startswith("first second")
    assert stream.getvalue().count("\n") == 1
    assert len(stream.getvalue()) <= 513
    assert stream.flushes == 1
