from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class CommandType(StrEnum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


class InputKind(StrEnum):
    EMPTY = "empty"
    MESSAGE = "message"
    COMMAND = "command"


class InteractionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"


@dataclass(frozen=True)
class ParsedInput:
    kind: InputKind
    text: str = ""
    identifier: str = ""
    arguments: str = ""


CommandHandler = Callable[[Any, str], Awaitable[None]]


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description: str
    usage: str
    command_type: CommandType
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    argument_hint: str | None = None
    hidden: bool = False


class CommandRegistrationError(RuntimeError):
    pass


class CommandUsageError(RuntimeError):
    pass


class CommandExecutionError(RuntimeError):
    pass


def parse_input(raw: str) -> ParsedInput:
    clean = raw.strip()
    if not clean:
        return ParsedInput(InputKind.EMPTY)
    if not clean.startswith("/"):
        return ParsedInput(InputKind.MESSAGE, text=clean)
    token, separator, arguments = clean.partition(" ")
    return ParsedInput(
        InputKind.COMMAND,
        identifier=token[1:],
        arguments=arguments.strip() if separator else "",
    )


class CommandRegistry:
    def __init__(self, definitions: Iterable[CommandDefinition]) -> None:
        ordered = tuple(definitions)
        index: dict[str, CommandDefinition] = {}
        for definition in ordered:
            for identifier in (definition.name, *definition.aliases):
                self._validate_identifier(identifier)
                key = identifier.casefold()
                if key in index:
                    raise CommandRegistrationError(
                        f"Command identifier conflict: {identifier}"
                    )
                index[key] = definition
        self._definitions = tuple(
            sorted(ordered, key=lambda item: (item.name.casefold(), item.name))
        )
        self._index = MappingProxyType(index)

    @staticmethod
    def _validate_identifier(identifier: str) -> None:
        if not identifier or "/" in identifier or any(
            character.isspace() for character in identifier
        ):
            raise CommandRegistrationError(
                f"Invalid command identifier: {identifier or '<empty>'}"
            )

    def resolve(self, identifier: str) -> CommandDefinition | None:
        return self._index.get(identifier.casefold())

    def public_definitions(self) -> tuple[CommandDefinition, ...]:
        return tuple(item for item in self._definitions if not item.hidden)

    def completion_candidates(self, prefix: str) -> tuple[str, ...]:
        clean = prefix[1:] if prefix.startswith("/") else prefix
        normalized = clean.casefold()
        values = {
            f"/{identifier}"
            for definition in self.public_definitions()
            for identifier in (definition.name, *definition.aliases)
            if identifier.casefold().startswith(normalized)
        }
        return tuple(sorted(values, key=lambda item: (item.casefold(), item)))
