from __future__ import annotations

import asyncio

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
        self.permission = PermissionMode.DEFAULT

    async def compact_context(self): self.compactions += 1
    def session_status(self): return ConversationStatus("s-1", "safe title", True, 4, False)
    def memory_status(self): return MemoryRuntimeStatus(2, 3, 10, 100, 200, 25600, MemoryUpdateState.RUNNING)
    def context_status(self): return ContextRuntimeStatus(False, 3)
    def permission_mode(self): return self.permission
    def set_permission_mode(self, mode): self.permission = mode


def dispatch(name: str, arguments: str = "", ui=None, runtime=None):
    ui = ui or FakeUI()
    runtime = runtime or FakeRuntime()
    dispatcher = CommandDispatcher(create_builtin_command_registry(), ui, runtime)
    asyncio.run(dispatcher.dispatch(ParsedInput(InputKind.COMMAND, identifier=name, arguments=arguments)))
    return ui, runtime


def test_builtin_metadata_is_exact() -> None:
    registry = create_builtin_command_registry()
    assert [item.name for item in registry.public_definitions()] == [
        "clear", "compact", "do", "help", "memory", "permission", "plan", "review", "session", "status"
    ]
    assert registry.resolve("permissions").name == "permission"
    assert registry.resolve("quit").name == "exit"
    assert registry.resolve("exit").hidden is True
    assert registry.resolve("review").command_type is CommandType.PROMPT
    assert registry.resolve("plan").command_type is CommandType.UI


def test_help_is_registry_driven_and_hides_exit() -> None:
    ui, _ = dispatch("help")
    output = ui.messages[0]
    assert output.count(" - ") == 10
    assert "/permissions" in output
    assert "/exit" not in output and "/quit" not in output
    ui, _ = dispatch("help", "/permissions")
    assert "Usage: /permission [strict|default|allow]" in ui.messages[0]
    assert "Aliases: /permissions" in ui.messages[0]
    ui, _ = dispatch("help", "exit")
    assert ui.errors == ["Unknown command '/exit'. Use /help."]


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


def test_compact_review_and_exit_take_exact_paths() -> None:
    ui, runtime = dispatch("compact")
    assert runtime.compactions == 1 and ui.sent == []
    dispatch("review", ui=ui, runtime=runtime)
    assert ui.sent == [(REVIEW_PROMPT, True)]
    assert ui.state.mode is InteractionMode.DEFAULT
    dispatch("quit", ui=ui, runtime=runtime)
    assert ui.state.exit_requested is True


def test_review_prompt_is_fixed_and_has_no_runtime_interpolation() -> None:
    first, _ = dispatch("review")
    second, _ = dispatch("review")
    assert first.sent == second.sent == [(REVIEW_PROMPT, True)]
    assert "uncommitted Git changes" in REVIEW_PROMPT


@pytest.mark.parametrize("name", ["compact", "clear", "plan", "do", "session", "memory", "status", "review", "exit"])
def test_no_argument_commands_reject_arguments(name: str) -> None:
    ui, _ = dispatch(name, "extra")
    assert ui.errors and ui.errors[0].startswith("Usage: ")
