from __future__ import annotations

from .contracts import CommandContext, CommandRuntime, CommandUI
from .core import (
    CommandExecutionError,
    CommandRegistry,
    CommandUsageError,
    InputKind,
    ParsedInput,
)


class CommandDispatcher:
    def __init__(
        self,
        registry: CommandRegistry,
        ui: CommandUI,
        runtime: CommandRuntime,
    ) -> None:
        self._registry = registry
        self._context = CommandContext(registry, ui, runtime)

    async def dispatch(self, invocation: ParsedInput) -> None:
        if invocation.kind is not InputKind.COMMAND:
            raise ValueError("CommandDispatcher only accepts command input.")
        definition = self._registry.resolve(invocation.identifier)
        if definition is None:
            self._context.ui.show_error(
                f"Unknown command '/{invocation.identifier}'. Use /help."
            )
            return
        try:
            await definition.handler(self._context, invocation.arguments)
        except CommandUsageError:
            self._context.ui.show_error(f"Usage: {definition.usage}")
        except CommandExecutionError as exc:
            self._context.ui.show_error(str(exc))
        except Exception:
            self._context.ui.show_error(
                f"Command '/{definition.name}' failed."
            )
