from __future__ import annotations

from mewcode.permissions import PermissionMode
from mewcode.subagents import (
    SubagentTaskSnapshot,
    SubagentTaskStatus,
    TaskCancelResult,
)
from mewcode.worktrees import WorktreeDeleteStatus

from .contracts import CommandContext
from .core import (
    CommandDefinition,
    CommandExecutionError,
    CommandRegistry,
    CommandType,
    CommandUsageError,
    InteractionMode,
)


# Compatibility export only. /review is now supplied by the built-in review Skill.
REVIEW_PROMPT = ""


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


async def _reset(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    await context.runtime.reset_conversation()
    context.ui.set_interaction_mode(InteractionMode.DEFAULT)
    context.ui.refresh_status()


async def _exit(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    context.ui.request_exit()


def _progress_summary(snapshot: SubagentTaskSnapshot) -> str:
    progress = snapshot.progress
    if progress is None:
        return "n/a"
    text = " ".join(progress.message.splitlines())[:160]
    return f"iteration={progress.iteration} phase={progress.phase[:64]} message={text}"


def _task_label(snapshot: SubagentTaskSnapshot) -> str:
    role = snapshot.role or "fork"
    worktree = (
        f" worktree={snapshot.worktree.state}:{snapshot.worktree.path}"
        if snapshot.worktree is not None
        else ""
    )
    return (
        f"{snapshot.task_id} kind={snapshot.kind.value} role={role[:64]} "
        f"placement={snapshot.placement.value} status={snapshot.status.value} "
        f"created={snapshot.created_at.isoformat()} progress={_progress_summary(snapshot)}{worktree}"
    )


async def _tasks(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    snapshots = context.runtime.list_subagent_tasks()
    if not snapshots:
        context.ui.show_message("No subagent tasks.")
        return
    active = [item for item in snapshots if item.status.active]
    terminal = [item for item in snapshots if item.status.terminal]
    lines = ["Active subagent tasks:"]
    lines.extend(f"  {_task_label(item)}" for item in active)
    if not active:
        lines.append("  none")
    lines.append("Terminal subagent tasks:")
    lines.extend(f"  {_task_label(item)}" for item in terminal)
    if not terminal:
        lines.append("  none")
    context.ui.show_message("\n".join(lines))


def _task_detail(snapshot: SubagentTaskSnapshot) -> str:
    usage = snapshot.usage
    lines = [
        f"task: {snapshot.task_id}",
        f"kind: {snapshot.kind.value}",
        f"role: {snapshot.role or 'fork'}",
        f"profile: {snapshot.profile_name}",
        f"placement: {snapshot.placement.value}",
        f"status: {snapshot.status.value}",
        f"created: {snapshot.created_at.isoformat()}",
        f"started: {snapshot.started_at.isoformat() if snapshot.started_at else 'n/a'}",
        f"finished: {snapshot.finished_at.isoformat() if snapshot.finished_at else 'n/a'}",
        f"progress: {_progress_summary(snapshot)}",
        "tokens: "
        f"in={_token(usage.input_tokens)} out={_token(usage.output_tokens)} "
        f"total={_token(usage.total_tokens)} "
        f"cache-read={_token(usage.cache_read_tokens)} "
        f"cache-write={_token(usage.cache_write_tokens)}",
        f"truncated: {'true' if snapshot.truncated else 'false'}",
    ]
    if snapshot.status.terminal:
        lines.append(f"result:\n{snapshot.result}")
        if snapshot.error:
            lines.append(f"error:\n{snapshot.error}")
    if snapshot.worktree is not None:
        lines.extend(
            (
                f"worktree-state: {snapshot.worktree.state}",
                f"worktree-path: {snapshot.worktree.path}",
                f"worktree-branch: {snapshot.worktree.branch_ref}",
            )
        )
        if snapshot.worktree.reason:
            lines.append(f"worktree-reason: {snapshot.worktree.reason}")
    return "\n".join(lines)


async def _task(context: CommandContext, arguments: str) -> None:
    tokens = arguments.split()
    if len(tokens) == 1:
        if tokens[0] == "cancel":
            raise CommandUsageError()
        snapshot = context.runtime.get_subagent_task(tokens[0])
        if snapshot is None:
            raise CommandExecutionError(f"Unknown subagent task '{tokens[0]}'.")
        context.ui.show_message(_task_detail(snapshot))
        return
    if len(tokens) == 2 and tokens[0] == "cancel":
        task_id = tokens[1]
        result = await context.runtime.cancel_subagent_task(task_id)
        messages = {
            TaskCancelResult.REQUESTED: f"Cancellation requested for subagent task {task_id}.",
            TaskCancelResult.ALREADY_TERMINAL: f"Subagent task {task_id} is already terminal.",
            TaskCancelResult.ALREADY_REQUESTED: f"Cancellation was already requested for subagent task {task_id}.",
            TaskCancelResult.NOT_FOUND: f"Unknown subagent task '{task_id}'.",
        }
        context.ui.show_message(messages[result])
        return
    raise CommandUsageError()


async def _worktrees(context: CommandContext, arguments: str) -> None:
    _no_arguments(arguments)
    statuses = await context.runtime.list_worktrees()
    if not statuses:
        context.ui.show_message("No managed Worktrees.")
        return
    lines = ["Managed Worktrees:"]
    for item in statuses:
        reason = f" reason={item.retained_reason}" if item.retained_reason else ""
        lines.append(
            f"  {item.name} state={item.state.value} path={item.path} "
            f"branch={item.branch_ref}{reason}"
        )
    context.ui.show_message("\n".join(lines))


async def _worktree(context: CommandContext, arguments: str) -> None:
    tokens = arguments.split()
    if len(tokens) == 3 and tokens[0] == "delete" and tokens[2] == "--force":
        name, force = tokens[1], True
    elif len(tokens) == 2 and tokens[0] == "delete":
        name, force = tokens[1], False
    else:
        raise CommandUsageError()
    result = await context.runtime.delete_worktree(name, force=force)
    messages = {
        WorktreeDeleteStatus.DELETED: "Deleted managed Worktree",
        WorktreeDeleteStatus.ALREADY_ABSENT: "Managed Worktree is already absent",
        WorktreeDeleteStatus.RETAINED: "Retained managed Worktree",
        WorktreeDeleteStatus.ACTIVE: "Managed Worktree is active",
        WorktreeDeleteStatus.REJECTED: "Rejected managed Worktree deletion",
    }
    suffix = f": {result.reason}" if result.reason else "."
    context.ui.show_message(f"{messages[result.status]} '{name}'{suffix}")


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
        CommandDefinition("tasks", "List subagent tasks.", "/tasks", CommandType.LOCAL, _tasks),
        CommandDefinition("task", "Show or cancel a subagent task.", "/task <id>|cancel <id>", CommandType.LOCAL, _task, argument_hint="<id>|cancel <id>"),
        CommandDefinition("worktrees", "List managed Worktrees.", "/worktrees", CommandType.LOCAL, _worktrees),
        CommandDefinition("worktree", "Delete a managed Worktree.", "/worktree delete <name> [--force]", CommandType.LOCAL, _worktree, argument_hint="delete <name> [--force]"),
        CommandDefinition("reset", "Reset the current conversation state.", "/reset", CommandType.LOCAL, _reset),
        CommandDefinition("exit", "Exit MewCode.", "/exit", CommandType.LOCAL, _exit, aliases=("quit",), hidden=True),
    )
    return CommandRegistry(definitions)


def create_skill_command_definition(name: str, description: str) -> CommandDefinition:
    async def invoke(context: CommandContext, arguments: str) -> None:
        raw = context.invocation.text if context.invocation is not None else f"/{name}"
        await context.runtime.invoke_skill(name, arguments, raw)

    return CommandDefinition(
        name,
        description,
        f"/{name} [input]",
        CommandType.PROMPT,
        invoke,
        argument_hint="[input]",
    )
