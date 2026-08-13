from __future__ import annotations

from collections.abc import AsyncIterator

from mewcode.agent import AgentControlContext, AgentControlOperation, AgentEvent
from mewcode.tools import (
    PermissionTargetKind,
    ToolPermissionSpec,
    ToolResult,
    ToolSafety,
)

from .coordinator import SubagentCoordinationError, SubagentCoordinator
from .models import SubagentPlacement, SubagentTaskStatus
from .tasks import SubagentTaskHandle, SubagentTaskManager


class _FrozenSchemaDict(dict):
    def _reject_mutation(self, *args, **kwargs):
        del args, kwargs
        raise TypeError("The agent tool schema is immutable.")

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    clear = _reject_mutation
    pop = _reject_mutation
    popitem = _reject_mutation
    setdefault = _reject_mutation
    update = _reject_mutation
    __ior__ = _reject_mutation


class _FrozenSchemaList(list):
    def _reject_mutation(self, *args, **kwargs):
        del args, kwargs
        raise TypeError("The agent tool schema is immutable.")

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    __iadd__ = _reject_mutation
    __imul__ = _reject_mutation
    append = _reject_mutation
    clear = _reject_mutation
    extend = _reject_mutation
    insert = _reject_mutation
    pop = _reject_mutation
    remove = _reject_mutation
    reverse = _reject_mutation
    sort = _reject_mutation


def _freeze_schema(value):
    if isinstance(value, dict):
        return _FrozenSchemaDict(
            (key, _freeze_schema(item)) for key, item in value.items()
        )
    if isinstance(value, list):
        return _FrozenSchemaList(_freeze_schema(item) for item in value)
    return value


AGENT_TOOL_SCHEMA = _freeze_schema(
    {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["defined", "fork"]},
            "task": {"type": "string"},
            "role": {"type": "string"},
            "background": {"type": "boolean"},
        },
        "required": ["type", "task"],
        "additionalProperties": False,
    }
)


class AgentTool:
    name = "agent"
    description = (
        "Delegate an independent task to a defined role or forked parent context."
    )
    parameters_schema = AGENT_TOOL_SCHEMA
    safety = ToolSafety.READ_ONLY
    permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL, "agent")

    def __init__(
        self,
        coordinator: SubagentCoordinator,
        task_manager: SubagentTaskManager,
    ) -> None:
        self._coordinator = coordinator
        self._task_manager = task_manager

    def control_operation(
        self,
        arguments: dict[str, object],
        context: AgentControlContext | None,
    ) -> AgentControlOperation:
        return SubagentDelegationOperation(
            self._coordinator,
            self._task_manager,
            arguments,
            context,
        )

    async def execute(self, arguments):
        raise RuntimeError("AgentTool executes through its control operation.")


class SubagentDelegationOperation:
    def __init__(
        self,
        coordinator: SubagentCoordinator,
        task_manager: SubagentTaskManager,
        arguments: dict[str, object],
        context: AgentControlContext | None,
    ) -> None:
        self._coordinator = coordinator
        self._task_manager = task_manager
        self._arguments = dict(arguments)
        self._context = context
        self._handle: SubagentTaskHandle | None = None
        self._result: ToolResult | None = None
        self._consumed = False
        self._cancel_requested = False

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._consumed:
            raise RuntimeError("A subagent delegation operation can only run once.")
        self._consumed = True
        try:
            launch = self._coordinator.prepare(self._arguments, self._context)
            handle = await self._task_manager.start(launch)
            self._handle = handle
        except (SubagentCoordinationError, RuntimeError, ValueError) as exc:
            self._result = ToolResult(
                False,
                "agent",
                "",
                str(exc)[:512],
            )
            return
        if self._cancel_requested and launch.placement is SubagentPlacement.FOREGROUND:
            await self._task_manager.cancel(handle.task_id)
        if launch.placement is SubagentPlacement.BACKGROUND:
            self._result = _background_result(handle)
            return
        async for event in handle.foreground_events():
            yield event
        snapshot = handle.snapshot
        if snapshot is None:
            self._result = ToolResult(
                False,
                "agent",
                "",
                "The subagent task disappeared before producing a result.",
            )
            return
        if snapshot.placement is SubagentPlacement.BACKGROUND:
            self._result = _background_result(handle)
            return
        ok = snapshot.status is SubagentTaskStatus.COMPLETED
        self._result = ToolResult(
            ok,
            "agent",
            snapshot.result if ok else "",
            None if ok else (snapshot.error or f"Subagent task {snapshot.status.value}."),
            {
                "task_id": snapshot.task_id,
                "kind": snapshot.kind.value,
                "placement": snapshot.placement.value,
                "status": snapshot.status.value,
                "truncated": snapshot.truncated,
                "usage": _usage_metadata(snapshot.usage),
            },
        )

    @property
    def result(self) -> ToolResult:
        if self._result is None:
            raise RuntimeError("The subagent delegation operation has not completed.")
        return self._result

    async def cancel(self) -> None:
        self._cancel_requested = True
        handle = self._handle
        if handle is None:
            return
        snapshot = handle.snapshot
        if (
            snapshot is not None
            and snapshot.status.active
            and snapshot.placement is SubagentPlacement.FOREGROUND
        ):
            await self._task_manager.cancel(handle.task_id)


def _background_result(handle: SubagentTaskHandle) -> ToolResult:
    snapshot = handle.snapshot
    if snapshot is None:
        return ToolResult(False, "agent", "", "The subagent task was not registered.")
    return ToolResult(
        True,
        "agent",
        f"Subagent task {snapshot.task_id} is running in the background.",
        metadata={
            "task_id": snapshot.task_id,
            "kind": snapshot.kind.value,
            "placement": snapshot.placement.value,
            "status": snapshot.status.value,
        },
    )


def _usage_metadata(usage) -> dict[str, int | None]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
    }
