from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from mewcode.commands import (
    CommandDefinition,
    CommandDispatcher,
    CommandRegistry,
    CommandType,
    InputKind,
    InteractionMode,
    InteractionState,
    ParsedInput,
    REVIEW_PROMPT,
    create_builtin_command_registry,
)
from mewcode.context import ContextRuntimeStatus
from mewcode.continuity import MemoryRuntimeStatus, MemoryUpdateState
from mewcode.conversation import ConversationStatus
from mewcode.permissions import PermissionMode
from mewcode.providers import TokenUsage, UsageSnapshot
from mewcode.subagents import (
    SubagentKind,
    SubagentParent,
    SubagentPlacement,
    SubagentProgress,
    SubagentTaskSnapshot,
    SubagentTaskStatus,
    TaskCancelResult,
)
from mewcode.worktrees import (
    WorktreeDeleteResult,
    WorktreeDeleteStatus,
    WorktreeState,
    WorktreeStatus,
)


class FakeUI:
    def __init__(self) -> None:
        self.state = InteractionState()
        self.messages = []
        self.errors = []
        self.sent = []
        self.clears = 0
        self.refreshes = 0

    def show_message(self, message): self.messages.append(message)
    def show_error(self, message): self.errors.append(message)
    def clear_display(self): self.clears += 1
    async def send_user_message(self, message, *, read_only=False): self.sent.append((message, read_only))
    def interaction_mode(self): return self.state.mode
    def set_interaction_mode(self, mode): self.state.mode = mode
    def token_usage(self): return UsageSnapshot(TokenUsage(1, 2, 3, None, 0), 2, 1)
    def refresh_status(self): self.refreshes += 1
    def request_exit(self): self.state.exit_requested = True


class FakeRuntime:
    def __init__(self) -> None:
        self.compactions = 0
        self.resets = 0
        self.permission = PermissionMode.DEFAULT
        self.tasks = ()
        self.cancel_result = TaskCancelResult.NOT_FOUND
        self.cancelled_ids = []
        self.worktrees = ()
        self.deleted_worktrees = []
        self.delete_result = WorktreeDeleteResult(WorktreeDeleteStatus.ALREADY_ABSENT)

    async def compact_context(self): self.compactions += 1
    async def reset_conversation(self): self.resets += 1
    def session_status(self): return ConversationStatus("s-1", "safe title", True, 4, False)
    def memory_status(self): return MemoryRuntimeStatus(2, 3, 10, 100, 200, 25600, MemoryUpdateState.RUNNING)
    def context_status(self): return ContextRuntimeStatus(False, 3)
    def permission_mode(self): return self.permission
    def set_permission_mode(self, mode): self.permission = mode
    def list_subagent_tasks(self): return self.tasks
    def get_subagent_task(self, task_id): return next((item for item in self.tasks if item.task_id == task_id), None)
    async def cancel_subagent_task(self, task_id):
        self.cancelled_ids.append(task_id)
        return self.cancel_result
    async def list_worktrees(self): return self.worktrees
    async def delete_worktree(self, name, *, force):
        self.deleted_worktrees.append((name, force))
        return self.delete_result


def dispatch(name: str, arguments: str = "", ui=None, runtime=None):
    ui = ui or FakeUI()
    runtime = runtime or FakeRuntime()
    dispatcher = CommandDispatcher(create_builtin_command_registry(), ui, runtime)
    asyncio.run(dispatcher.dispatch(ParsedInput(InputKind.COMMAND, identifier=name, arguments=arguments)))
    return ui, runtime


def test_builtin_metadata_is_exact() -> None:
    registry = create_builtin_command_registry()
    assert [item.name for item in registry.public_definitions()] == [
        "clear", "compact", "do", "help", "memory", "permission", "plan", "reset", "session", "status", "task", "tasks", "worktree", "worktrees"
    ]
    assert registry.resolve("permissions").name == "permission"
    assert registry.resolve("quit").name == "exit"
    assert registry.resolve("exit").hidden is True
    assert registry.resolve("reset").command_type is CommandType.LOCAL
    assert registry.resolve("plan").command_type is CommandType.UI


def test_help_is_registry_driven_and_hides_exit() -> None:
    ui, _ = dispatch("help")
    output = ui.messages[0]
    assert output.count(" - ") == 14
    assert "/permissions" in output
    assert "/exit" not in output and "/quit" not in output
    ui, _ = dispatch("help", "/permissions")
    assert "Usage: /permission [strict|default|allow]" in ui.messages[0]
    assert "Aliases: /permissions" in ui.messages[0]
    ui, _ = dispatch("help", "exit")
    assert ui.errors == ["Unknown command '/exit'. Use /help."]


def test_worktrees_list_and_strict_delete_commands(tmp_path) -> None:
    runtime = FakeRuntime()
    runtime.worktrees = (
        WorktreeStatus(
            "task/abc",
            WorktreeState.RETAINED,
            tmp_path / "tree",
            "refs/heads/mewcode/worktree/task/abc",
            datetime.now(timezone.utc),
            "tracked changes",
        ),
    )
    ui, _ = dispatch("worktrees", runtime=runtime)
    assert "task/abc" in ui.messages[0]
    runtime.delete_result = WorktreeDeleteResult(WorktreeDeleteStatus.DELETED)
    dispatch("worktree", "delete task/abc --force", runtime=runtime)
    assert runtime.deleted_worktrees == [("task/abc", True)]
    ui, _ = dispatch("worktree", "delete --force task/abc", runtime=runtime)
    assert ui.errors


def test_help_and_alias_details_share_the_same_registry_metadata() -> None:
    canonical, _ = dispatch("help", "permission")
    alias, _ = dispatch("help", "/permissions")
    assert canonical.messages == alias.messages


def test_registry_is_extensible_without_changing_help_or_dispatch() -> None:
    calls = []

    async def custom(context, arguments: str) -> None:
        calls.append(arguments)
        context.ui.show_message("custom result")

    builtin = create_builtin_command_registry()
    registry = CommandRegistry(
        [
            builtin.resolve("help"),
            CommandDefinition(
                "custom",
                "Custom command.",
                "/custom [value]",
                CommandType.LOCAL,
                custom,
                argument_hint="[value]",
            ),
        ]
    )
    ui, runtime = FakeUI(), FakeRuntime()
    dispatcher = CommandDispatcher(registry, ui, runtime)
    asyncio.run(
        dispatcher.dispatch(ParsedInput(InputKind.COMMAND, identifier="help"))
    )
    asyncio.run(
        dispatcher.dispatch(
            ParsedInput(InputKind.COMMAND, identifier="custom", arguments="value")
        )
    )

    assert "/custom" in ui.messages[0]
    assert registry.completion_candidates("/cus") == ("/custom",)
    assert calls == ["value"]
    assert ui.messages[-1] == "custom result"


def test_clear_plan_and_do_only_change_ui_state() -> None:
    ui, runtime = dispatch("plan")
    assert ui.state.mode is InteractionMode.PLAN and ui.refreshes == 1
    dispatch("clear", ui=ui, runtime=runtime)
    assert ui.clears == 1 and ui.state.mode is InteractionMode.PLAN
    dispatch("do", ui=ui, runtime=runtime)
    assert ui.state.mode is InteractionMode.DEFAULT
    assert ui.sent == [] and runtime.compactions == 0


def test_session_and_memory_formats_are_safe() -> None:
    ui, runtime = dispatch("session")
    assert ui.messages == ["session: id=s-1 state=resumed messages=4 operation=idle\ntitle: safe title"]
    dispatch("memory", ui=ui, runtime=runtime)
    assert ui.messages[-1] == "memory: project=2 user=3 update=running\nindex: lines=10/200 bytes=100/25600"


@pytest.mark.parametrize("mode", ["strict", "DEFAULT", "allow"])
def test_permission_queries_and_changes_all_modes(mode: str) -> None:
    ui, runtime = dispatch("permission", mode)
    assert runtime.permission.value == mode.casefold()
    assert ui.messages == [f"permission: {mode.casefold()}"]
    ui, _ = dispatch("permissions", runtime=runtime)
    assert ui.messages == [f"permission: {mode.casefold()}"]


def test_status_includes_all_core_fields_and_na() -> None:
    ui, _ = dispatch("status")
    output = ui.messages[0]
    for text in ("mode: [DEFAULT]", "session: s-1", "permission: default", "in=1", "out=2", "total=3", "cache-read=n/a", "requests=2", "unreported=1", "automatic-compaction=disabled", "project=2 user=3 update=running"):
        assert text in output
    assert ui.refreshes == 1


def test_compact_reset_and_exit_take_exact_paths() -> None:
    ui, runtime = dispatch("compact")
    assert runtime.compactions == 1 and ui.sent == []
    ui.state.mode = InteractionMode.PLAN
    dispatch("reset", ui=ui, runtime=runtime)
    assert runtime.resets == 1
    assert ui.state.mode is InteractionMode.DEFAULT
    dispatch("quit", ui=ui, runtime=runtime)
    assert ui.state.exit_requested is True


def test_reset_failure_does_not_change_plan_mode() -> None:
    class FailingRuntime(FakeRuntime):
        async def reset_conversation(self):
            raise RuntimeError("reset failed")

    ui = FakeUI()
    ui.state.mode = InteractionMode.PLAN
    ui, _ = dispatch("reset", ui=ui, runtime=FailingRuntime())
    assert ui.state.mode is InteractionMode.PLAN
    assert ui.errors == ["Command '/reset' failed."]


def test_review_prompt_compatibility_export_is_empty() -> None:
    assert REVIEW_PROMPT == ""


def _task_snapshot(
    task_id="task-1",
    *,
    status=SubagentTaskStatus.RUNNING,
    role="reviewer",
    usage=TokenUsage.zero(),
):
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    return SubagentTaskSnapshot(
        task_id,
        SubagentKind.DEFINED if role else SubagentKind.FORK,
        status,
        SubagentPlacement.BACKGROUND,
        role,
        "main",
        SubagentParent("parent", 1),
        now,
        now,
        now if status.terminal else None,
        SubagentProgress(2, "model", "safe\nprogress"),
        "final result" if status.terminal else "",
        "failed" if status is SubagentTaskStatus.FAILED else None,
        False,
        usage,
        False,
    )


def test_tasks_lists_safe_grouped_summaries_and_rejects_arguments() -> None:
    runtime = FakeRuntime()
    ui, _ = dispatch("tasks", runtime=runtime)
    assert ui.messages == ["No subagent tasks."]

    runtime.tasks = (
        _task_snapshot(),
        _task_snapshot("fork-1", status=SubagentTaskStatus.COMPLETED, role=None),
    )
    ui, _ = dispatch("tasks", runtime=runtime)
    output = ui.messages[0]
    assert "Active subagent tasks:" in output
    assert "Terminal subagent tasks:" in output
    assert "role=fork" in output
    assert "safe progress" in output
    assert "final result" not in output
    ui, _ = dispatch("tasks", "extra", runtime=runtime)
    assert ui.errors[0] == "Usage: /tasks"


def test_task_detail_is_local_nonblocking_and_formats_unknown_usage() -> None:
    runtime = FakeRuntime()
    runtime.tasks = (
        _task_snapshot(
            status=SubagentTaskStatus.COMPLETED,
            usage=TokenUsage(None, 2, None, None, None),
        ),
    )
    ui, _ = dispatch("task", "task-1", runtime=runtime)
    output = ui.messages[0]
    assert "status: completed" in output
    assert "result:\nfinal result" in output
    assert "in=n/a out=2 total=n/a cache-read=n/a cache-write=n/a" in output
    ui, _ = dispatch("task", "missing", runtime=runtime)
    assert ui.errors == ["Unknown subagent task 'missing'."]


@pytest.mark.parametrize(
    ("result", "text"),
    [
        (TaskCancelResult.REQUESTED, "Cancellation requested"),
        (TaskCancelResult.ALREADY_TERMINAL, "already terminal"),
        (TaskCancelResult.ALREADY_REQUESTED, "already requested"),
        (TaskCancelResult.NOT_FOUND, "Unknown subagent task"),
    ],
)
def test_task_cancel_formats_all_idempotent_results(result, text) -> None:
    runtime = FakeRuntime()
    runtime.cancel_result = result
    ui, _ = dispatch("task", "cancel task-1", runtime=runtime)
    assert runtime.cancelled_ids == ["task-1"]
    assert text in ui.messages[0]


@pytest.mark.parametrize("arguments", ["", "cancel", "cancel one extra", "other one"])
def test_task_rejects_invalid_token_combinations(arguments) -> None:
    ui, runtime = dispatch("task", arguments)
    assert ui.errors == ["Usage: /task <id>|cancel <id>"]
    assert runtime.cancelled_ids == []


@pytest.mark.parametrize("name", ["compact", "clear", "plan", "do", "session", "memory", "status", "reset", "exit"])
def test_no_argument_commands_reject_arguments(name: str) -> None:
    ui, _ = dispatch(name, "extra")
    assert ui.errors and ui.errors[0].startswith("Usage: ")
