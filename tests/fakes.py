from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any, TypeVar

from mewcode.providers import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ProviderEvent,
    ProviderFinished,
    ProviderFinishReason,
    ProviderToolCall,
)
from mewcode.tools import (
    PermissionTargetKind,
    ToolCallRequest,
    ToolExecution,
    ToolRegistry,
    ToolResult,
    ToolSafety,
    ToolPermissionSpec,
)

T = TypeVar("T")


async def collect_async(source: AsyncIterator[T]) -> list[T]:
    return [item async for item in source]


class ScriptedAsyncProvider:
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent] | BaseException]) -> None:
        self.scripts = list(scripts)
        self.calls: list[ModelRequest] = []

    async def stream_reply(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ProviderEvent]:
        self.calls.append(request)
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        saw_finish = False
        saw_tool_call = False
        for event in script:
            if isinstance(event, BaseException):
                raise event
            if isinstance(event, ProviderFinished):
                saw_finish = True
            elif isinstance(event, ProviderToolCall):
                saw_tool_call = True
            await asyncio.sleep(0)
            yield event
        if not saw_finish:
            reason = (
                ProviderFinishReason.TOOL_CALLS
                if saw_tool_call
                else ProviderFinishReason.NATURAL
            )
            yield ProviderFinished(reason)

    def assistant_messages(self, response: ModelResponse) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="assistant",
                content={
                    "text": response.text,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                        for call in response.tool_calls
                    ],
                },
            )
        ]

    def tool_result_messages(
        self, executions: Sequence[ToolExecution]
    ) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="tool",
                content=[
                    {
                        "id": execution.request.id,
                        "ok": execution.result.ok,
                        "content": execution.result.content,
                        "error": execution.result.error,
                    }
                    for execution in executions
                ],
            )
        ]


class ControlledTool:
    description = "A controllable async test tool."
    parameters_schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": [],
    }
    permission_spec = ToolPermissionSpec(
        "value", PermissionTargetKind.COMMAND, default="test"
    )

    def __init__(
        self,
        name: str,
        safety: ToolSafety = ToolSafety.READ_ONLY,
        *,
        result: ToolResult | None = None,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.name = name
        self.safety = safety
        self.result = result
        self.started = started
        self.release = release
        self.calls = calls if calls is not None else []
        self.cancelled = False

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(self.name)
        if self.started is not None:
            self.started.set()
        try:
            if self.release is not None:
                await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.result or ToolResult(
            ok=True,
            tool_name=self.name,
            content=str(arguments.get("value", self.name)),
        )


def tool_call(call_id: str, name: str, **arguments: Any) -> ToolCallRequest:
    return ToolCallRequest(
        id=call_id,
        name=name,
        arguments=arguments,
        raw_arguments="{}",
    )
