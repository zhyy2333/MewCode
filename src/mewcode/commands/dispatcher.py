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
        self._ui = ui
        self._runtime = runtime

    async def dispatch(self, invocation: ParsedInput) -> None:
        if invocation.kind is not InputKind.COMMAND:
            raise ValueError("CommandDispatcher only accepts command input.")
        definition = self._registry.resolve(invocation.identifier)
        if definition is None:
            self._ui.show_error(
                f"Unknown command '/{invocation.identifier}'. Use /help."
            )
            return
        try:
            context = CommandContext(
                self._registry, self._ui, self._runtime, invocation
            )
            await definition.handler(context, invocation.arguments)
        except CommandUsageError:
            self._ui.show_error(f"Usage: {definition.usage}")
        except CommandExecutionError as exc:
            self._ui.show_error(str(exc))
        except Exception:
            self._ui.show_error(
                f"Command '/{definition.name}' failed."
            )
