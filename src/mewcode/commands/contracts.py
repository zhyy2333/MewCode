from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mewcode.context import ContextRuntimeStatus
from mewcode.continuity import MemoryRuntimeStatus
from mewcode.conversation import ConversationStatus
from mewcode.permissions import PermissionMode
from mewcode.providers import UsageSnapshot

from .core import CommandRegistry, InteractionMode, ParsedInput


@dataclass
class InteractionState:
    mode: InteractionMode = InteractionMode.DEFAULT
    exit_requested: bool = False


class CommandUI(Protocol):
    def show_message(self, message: str) -> None: ...

    def show_error(self, message: str) -> None: ...

    def clear_display(self) -> None: ...

    async def send_user_message(
        self, message: str, *, read_only: bool = False
    ) -> None: ...

    def interaction_mode(self) -> InteractionMode: ...

    def set_interaction_mode(self, mode: InteractionMode) -> None: ...

    def token_usage(self) -> UsageSnapshot: ...

    def refresh_status(self) -> None: ...

    def request_exit(self) -> None: ...


class CommandRuntime(Protocol):
    async def compact_context(self) -> None: ...

    def session_status(self) -> ConversationStatus: ...

    def memory_status(self) -> MemoryRuntimeStatus: ...

    def context_status(self) -> ContextRuntimeStatus: ...

    def permission_mode(self) -> PermissionMode: ...

    def set_permission_mode(self, mode: PermissionMode) -> None: ...

    async def invoke_skill(
        self, name: str, input_text: str, raw_command: str
    ) -> None: ...

    async def reset_conversation(self) -> None: ...


@dataclass(frozen=True)
class CommandContext:
    registry: CommandRegistry
    ui: CommandUI
    runtime: CommandRuntime
    invocation: ParsedInput | None = None
