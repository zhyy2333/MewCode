from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any, TypeVar

from mewcode.providers import ChatMessage, ModelResponse, ProviderEvent
from mewcode.tools import (
    ToolCallRequest,
    ToolExecution,
    ToolRegistry,
    ToolResult,
    ToolSafety,
)

T = TypeVar("T")


async def collect_async(source: AsyncIterator[T]) -> list[T]:
    return [item async for item in source]


class ScriptedAsyncProvider:
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent] | BaseException]) -> None:
        self.scripts = list(scripts)
        self.calls: list[dict[str, Any]] = []

    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        return registry.to_openai_tools()

    async def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        self.calls.append({"messages": list(messages), "tools": tools})
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        for event in script:
            if isinstance(event, BaseException):
                raise event
            await asyncio.sleep(0)
            yield event

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
