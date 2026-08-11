from __future__ import annotations

import asyncio

from mewcode.commands import (
    CommandDefinition,
    CommandDispatcher,
    CommandExecutionError,
    CommandRegistry,
    CommandType,
    CommandUsageError,
    InputKind,
    ParsedInput,
)


class FakeUI:
    def __init__(self) -> None:
        self.messages = []
        self.errors = []
        self.sent = []

    def show_message(self, message): self.messages.append(message)
    def show_error(self, message): self.errors.append(message)
    def clear_display(self): pass
    async def send_user_message(self, message, *, read_only=False): self.sent.append((message, read_only))
    def interaction_mode(self): return None
    def set_interaction_mode(self, mode): pass
    def token_usage(self): return None
    def refresh_status(self): pass
    def request_exit(self): pass


class FakeRuntime:
    pass


def invocation(name="test", arguments=""):
    return ParsedInput(InputKind.COMMAND, identifier=name, arguments=arguments)


def test_dispatches_name_and_alias() -> None:
    calls = []

    async def handler(_context, arguments): calls.append(arguments)

    ui = FakeUI()
    registry = CommandRegistry([CommandDefinition("test", "d", "/test", CommandType.LOCAL, handler, aliases=("t",))])
    dispatcher = CommandDispatcher(registry, ui, FakeRuntime())
    asyncio.run(dispatcher.dispatch(invocation("TEST", "one")))
    asyncio.run(dispatcher.dispatch(invocation("T", "two")))
    assert calls == ["one", "two"]


def test_unknown_command_is_local_and_guides_to_help() -> None:
    ui = FakeUI()
    dispatcher = CommandDispatcher(CommandRegistry([]), ui, FakeRuntime())
    asyncio.run(dispatcher.dispatch(invocation("missing")))
    assert ui.errors == ["Unknown command '/missing'. Use /help."]
    assert ui.sent == []


def test_usage_safe_execution_and_privacy_errors_are_isolated() -> None:
    async def usage(_context, _arguments): raise CommandUsageError()
    async def safe(_context, _arguments): raise CommandExecutionError("Safe failure.")
    async def private(_context, _arguments): raise RuntimeError("secret stack detail")
    ui = FakeUI()
    registry = CommandRegistry([
        CommandDefinition("usage", "d", "/usage", CommandType.LOCAL, usage),
        CommandDefinition("safe", "d", "/safe", CommandType.LOCAL, safe),
        CommandDefinition("private", "d", "/private", CommandType.LOCAL, private),
    ])
    dispatcher = CommandDispatcher(registry, ui, FakeRuntime())
    for name in ("usage", "safe", "private"):
        asyncio.run(dispatcher.dispatch(invocation(name)))
    assert ui.errors == [
        "Usage: /usage",
        "Safe failure.",
        "Command '/private' failed.",
    ]
    assert "secret" not in " ".join(ui.errors)


def test_dispatcher_rejects_non_command_inputs() -> None:
    dispatcher = CommandDispatcher(CommandRegistry([]), FakeUI(), FakeRuntime())
    try:
        asyncio.run(dispatcher.dispatch(ParsedInput(InputKind.MESSAGE, text="hi")))
    except ValueError as exc:
        assert "only accepts" in str(exc)
    else:
        raise AssertionError("expected ValueError")
