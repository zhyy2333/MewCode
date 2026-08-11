from __future__ import annotations

from mewcode.permissions import PermissionMode

from .contracts import CommandContext
from .core import (
    CommandDefinition,
    CommandExecutionError,
    CommandRegistry,
    CommandType,
    CommandUsageError,
    InteractionMode,
)


REVIEW_PROMPT = """Review the current workspace's uncommitted Git changes. Inspect the working
tree and report only actionable findings, ordered by severity, with file and
line references where possible. Focus on defects, behavioral regressions,
security risks, and missing tests. Do not modify files. If there are no
findings, say so explicitly."""


def _no_arguments(arguments: str) -> None:
    if arguments:
        raise CommandUsageError()


def _format_help(registry: CommandRegistry, identifier: str = "") -> str:
    if not identifier:
        lines = ["Available commands:"]
        for definition in registry.public_definitions():
            aliases = (
                " (aliases: "
                + ", ".join(f"/{alias}" for alias in definition.aliases)
                + ")"
                if definition.aliases
                else ""
            )
            lines.append(f"  /{definition.name}{aliases} - {definition.description}")
        lines.append("Use /help <command> for details.")
        return "\n".join(lines)
    clean = identifier[1:] if identifier.startswith("/") else identifier
    definition = registry.resolve(clean)
    if definition is None or definition.hidden:
        raise CommandExecutionError(f"Unknown command '/{clean}'. Use /help.")
    aliases = (
        ", ".join(f"/{alias}" for alias in definition.aliases) or "none"
    )
    hint = definition.argument_hint or "none"
    return "\n".join(
        (
            f"/{definition.name} - {definition.description}",
            f"Usage: {definition.usage}",
            f"Arguments: {hint}",
            f"Aliases: {aliases}",
        )
    )


async def _help(context: CommandContext, arguments: str) -> None:
    context.ui.show_message(_format_help(context.registry, arguments))


async def _compact(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    await context.runtime.compact_context()


async def _clear(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.clear_display()
    context.ui.refresh_status()


async def _plan(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.set_interaction_mode(InteractionMode.PLAN)
    context.ui.refresh_status()


async def _do(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.set_interaction_mode(InteractionMode.DEFAULT)
    context.ui.refresh_status()


def _format_session(context: CommandContext) -> str:
    status = context.runtime.session_status()
    state = "resumed" if status.resumed else "new"
    operation = "busy" if status.busy else "idle"
    return (
        f"session: id={status.session_id} state={state} "
        f"messages={status.message_count} operation={operation}\n"
        f"title: {status.title}"
    )


async def _session(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.show_message(_format_session(context))


def _format_memory(context: CommandContext) -> str:
    status = context.runtime.memory_status()
    return (
        f"memory: project={status.project_notes} user={status.user_notes} "
        f"update={status.update_state.value}\n"
        f"index: lines={status.index_lines}/{status.max_index_lines} "
        f"bytes={status.index_bytes}/{status.max_index_bytes}"
    )


async def _memory(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.show_message(_format_memory(context))


async def _permission(context: CommandContext, arguments: str) -> None:
    if not arguments:
        context.ui.show_message(f"permission: {context.runtime.permission_mode().value}")
        return
    if len(arguments.split()) != 1:
        raise CommandUsageError()
    try:
        mode = PermissionMode(arguments.casefold())
    except ValueError as exc:
        raise CommandUsageError() from exc
    context.runtime.set_permission_mode(mode)
    context.ui.show_message(f"permission: {mode.value}")


def _token(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _format_status(context: CommandContext) -> str:
    session = context.runtime.session_status()
    memory = context.runtime.memory_status()
    context_state = context.runtime.context_status()
    snapshot = context.ui.token_usage()
    usage = snapshot.usage
    mode = context.ui.interaction_mode().value.upper()
    automatic = "enabled" if context_state.automatic_compaction_enabled else "disabled"
    return "\n".join(
        (
            f"mode: [{mode}]",
            f"session: {session.session_id}",
            f"permission: {context.runtime.permission_mode().value}",
            "tokens: "
            f"in={_token(usage.input_tokens)} out={_token(usage.output_tokens)} "
            f"total={_token(usage.total_tokens)} "
            f"cache-read={_token(usage.cache_read_tokens)} "
            f"cache-write={_token(usage.cache_write_tokens)} "
            f"requests={snapshot.request_count} "
            f"unreported={snapshot.unreported_request_count}",
            f"context: automatic-compaction={automatic} "
            f"consecutive-failures={context_state.consecutive_failures}",
            f"memory: project={memory.project_notes} user={memory.user_notes} "
            f"update={memory.update_state.value}",
        )
    )


async def _status(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.show_message(_format_status(context))
    context.ui.refresh_status()


async def _review(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    await context.ui.send_user_message(REVIEW_PROMPT, read_only=True)


async def _exit(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.request_exit()


def create_builtin_command_registry() -> CommandRegistry:
    definitions = (
        CommandDefinition("help", "Show command help.", "/help [command]", CommandType.LOCAL, _help, argument_hint="[command]"),
        CommandDefinition("compact", "Compact conversation context.", "/compact", CommandType.LOCAL, _compact),
        CommandDefinition("clear", "Clear the terminal display.", "/clear", CommandType.UI, _clear),
        CommandDefinition("plan", "Enter read-only plan mode.", "/plan", CommandType.UI, _plan),
        CommandDefinition("do", "Return to default mode.", "/do", CommandType.UI, _do),
        CommandDefinition("session", "Show the current session summary.", "/session", CommandType.LOCAL, _session),
        CommandDefinition("memory", "Show the safe memory summary.", "/memory", CommandType.LOCAL, _memory),
        CommandDefinition("permission", "Show or change permission mode.", "/permission [strict|default|allow]", CommandType.LOCAL, _permission, aliases=("permissions",), argument_hint="[strict|default|allow]"),
        CommandDefinition("status", "Show the current runtime status.", "/status", CommandType.LOCAL, _status),
        CommandDefinition("review", "Review uncommitted workspace changes.", "/review", CommandType.PROMPT, _review),
        CommandDefinition("exit", "Exit MewCode.", "/exit", CommandType.LOCAL, _exit, aliases=("quit",), hidden=True),
    )
    return CommandRegistry(definitions)
