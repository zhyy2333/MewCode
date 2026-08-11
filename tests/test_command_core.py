from __future__ import annotations

import pytest

from mewcode.commands.core import (
    CommandDefinition,
    CommandRegistrationError,
    CommandRegistry,
    CommandType,
    InputKind,
    parse_input,
)


async def noop(_context, _arguments: str) -> None:
    return None


def command(
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    hidden: bool = False,
) -> CommandDefinition:
    return CommandDefinition(
        name,
        f"Describe {name}",
        f"/{name}",
        CommandType.LOCAL,
        noop,
        aliases,
        hidden=hidden,
    )


def test_parse_empty_message_and_command_arguments() -> None:
    assert parse_input(" \t ").kind is InputKind.EMPTY
    assert parse_input("  Hello World  ").text == "Hello World"
    parsed = parse_input("  /HeLp    Keep  CASE  ")
    assert parsed.kind is InputKind.COMMAND
    assert parsed.identifier == "HeLp"
    assert parsed.arguments == "Keep  CASE"


def test_parse_uses_only_ascii_space_as_command_separator() -> None:
    parsed = parse_input("/help\tstatus")
    assert parsed.identifier == "help\tstatus"
    assert parsed.arguments == ""


@pytest.mark.parametrize("identifier", ["", "/bad", "two words", "tab\tname"])
def test_invalid_identifier_is_rejected(identifier: str) -> None:
    with pytest.raises(CommandRegistrationError):
        CommandRegistry([command(identifier)])


@pytest.mark.parametrize(
    "definitions",
    [
        [command("help"), command("HELP")],
        [command("help", aliases=("h",)), command("H")],
        [command("one", aliases=("same",)), command("two", aliases=("SAME",))],
        [command("one", aliases=("ONE",))],
    ],
)
def test_all_casefolded_conflicts_are_rejected(definitions) -> None:
    with pytest.raises(CommandRegistrationError, match="conflict"):
        CommandRegistry(definitions)


def test_registry_resolves_aliases_and_sorts_public_definitions() -> None:
    hidden = command("exit", aliases=("quit",), hidden=True)
    registry = CommandRegistry(
        [command("Status", aliases=("stats",)), hidden, command("help")]
    )
    assert registry.resolve("STATUS").name == "Status"
    assert registry.resolve("StAtS").name == "Status"
    assert registry.resolve("QUIT") is hidden
    assert [item.name for item in registry.public_definitions()] == ["help", "Status"]


def test_completion_candidates_are_deterministic_and_hide_private_names() -> None:
    registry = CommandRegistry(
        [
            command("permission", aliases=("permissions",)),
            command("plan"),
            command("exit", aliases=("quit",), hidden=True),
        ]
    )
    assert registry.completion_candidates("/P") == (
        "/permission",
        "/permissions",
        "/plan",
    )
    assert "/exit" not in registry.completion_candidates("")
    assert "/quit" not in registry.completion_candidates("")
