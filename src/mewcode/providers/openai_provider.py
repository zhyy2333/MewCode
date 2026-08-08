from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from mewcode.tools import ToolCallRequest, ToolExecution, ToolRegistry, ToolResult

from .base import (
    DEFAULT_MAX_TOKENS,
    ChatMessage,
    ModelResponse,
    ProviderError,
    ProviderEvent,
    ProviderProfile,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
)


class OpenAIProvider:
    def __init__(self, profile: ProviderProfile) -> None:
        self._profile = profile
        try:
            import openai
        except ImportError as exc:
            raise ProviderError("OpenAI SDK is not installed.") from exc

        self._client = openai.AsyncOpenAI(
            api_key=profile.api_key,
            base_url=profile.base_url,
        )

    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        return registry.to_openai_tools()

    async def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        request: dict[str, Any] = {
            "model": self._profile.model,
            "input": self._build_input(messages),
            "max_output_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if tools:
            request["tools"] = tools

        stream: Any = None
        usage_emitted = False
        try:
            parser = _OpenAIToolEventParser()
            stream = await self._client.responses.create(**request)
            async for event in stream:
                event_type = _get_event_attr(event, "type")
                if event_type == "response.output_text.delta":
                    delta = _get_event_attr(event, "delta") or ""
                    if delta:
                        yield ProviderTextDelta(delta)
                elif event_type == "error":
                    message = _get_event_attr(event, "message") or str(event)
                    raise ProviderError(f"OpenAI request failed: {message}")
                elif event_type in {
                    "response.output_item.added",
                    "response.output_item.done",
                    "response.function_call_arguments.delta",
                    "response.function_call_arguments.done",
                }:
                    tool_event = parser.consume(event)
                    if tool_event is not None:
                        yield tool_event
                elif event_type == "response.completed":
                    response = _get_event_attr(event, "response") or {}
                    yield ProviderUsage(_openai_usage(_get_event_attr(response, "usage")))
                    usage_emitted = True
            if not usage_emitted:
                yield ProviderUsage(TokenUsage())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise self._to_provider_error(exc) from exc
        finally:
            if stream is not None:
                close = getattr(stream, "close", None) or getattr(stream, "aclose", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result

    def _build_input(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        inputs: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message.content, dict) and message.content.get("type") in {
                "function_call",
                "function_call_output",
            }:
                inputs.append(message.content)
            else:
                inputs.append({"role": message.role, "content": message.content})
        return inputs

    def assistant_messages(self, response: ModelResponse) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        if response.text or not response.tool_calls:
            messages.append(ChatMessage(role="assistant", content=response.text))
        messages.extend(
            ChatMessage(
                role="assistant",
                content={
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": call.raw_arguments,
                },
            )
            for call in response.tool_calls
        )
        return messages

    def tool_result_messages(
        self, executions: Sequence[ToolExecution]
    ) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="tool",
                content={
                    "type": "function_call_output",
                    "call_id": execution.request.id,
                    "output": _tool_result_payload(execution.result),
                },
            )
            for execution in executions
        ]

    def _to_provider_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            message = exc.message
        else:
            message = str(exc).strip() or exc.__class__.__name__
        message = message.replace(self._profile.api_key, "[redacted]")
        if message.startswith("OpenAI request failed:"):
            return ProviderError(message)
        return ProviderError(f"OpenAI request failed: {message}")


def _tool_result_payload(result: ToolResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "content": result.content,
            "error": result.error,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
    )


class _OpenAIToolEventParser:
    def __init__(self) -> None:
        self._calls: dict[str, dict[str, Any]] = {}
        self._completed_item_ids: set[str] = set()

    def consume(self, event: Any) -> ProviderToolCall | None:
        event_type = _get_event_attr(event, "type")
        if event_type == "response.output_item.added":
            item = _get_event_attr(event, "item") or {}
            if _get_event_attr(item, "type") in {"function_call", "tool_call"}:
                item_id = _get_event_attr(item, "id") or _get_event_attr(item, "call_id") or ""
                self._calls[item_id] = {
                    "call_id": _get_event_attr(item, "call_id") or item_id,
                    "name": _get_event_attr(item, "name") or "",
                    "parts": [],
                }
            return None

        item_id = _get_event_attr(event, "item_id") or _get_event_attr(event, "call_id") or ""
        if event_type == "response.function_call_arguments.delta":
            call = self._calls.setdefault(
                item_id, {"call_id": item_id, "name": "", "parts": []}
            )
            call["parts"].append(_get_event_attr(event, "delta") or "")
            return None

        if event_type == "response.function_call_arguments.done":
            call = self._calls.pop(
                item_id, {"call_id": item_id, "name": "", "parts": []}
            )
            raw_arguments = _get_event_attr(event, "arguments")
            if raw_arguments is None:
                raw_arguments = "".join(call["parts"])
            name = _get_event_attr(event, "name") or call["name"]
            self._completed_item_ids.add(item_id)
            return ProviderToolCall(_build_tool_call(call["call_id"], name, raw_arguments or ""))

        if event_type == "response.output_item.done":
            item = _get_event_attr(event, "item") or {}
            if _get_event_attr(item, "type") not in {"function_call", "tool_call"}:
                return None
            item_id = _get_event_attr(item, "id") or _get_event_attr(item, "call_id") or ""
            if item_id in self._completed_item_ids:
                return None
            call = self._calls.pop(
                item_id,
                {
                    "call_id": _get_event_attr(item, "call_id") or item_id,
                    "name": _get_event_attr(item, "name") or "",
                    "parts": [],
                },
            )
            raw_arguments = _get_event_attr(item, "arguments")
            if raw_arguments is None:
                raw_arguments = "".join(call["parts"])
            self._completed_item_ids.add(item_id)
            return ProviderToolCall(
                _build_tool_call(
                    call["call_id"],
                    _get_event_attr(item, "name") or call["name"],
                    raw_arguments or "",
                )
            )
        return None


def _build_tool_call(call_id: str, name: str, raw_arguments: str) -> ToolCallRequest:
    try:
        arguments = json.loads(raw_arguments) if raw_arguments else {}
        if not isinstance(arguments, dict):
            arguments = {}
    except json.JSONDecodeError:
        arguments = {}
    return ToolCallRequest(
        id=call_id,
        name=name,
        arguments=arguments,
        raw_arguments=raw_arguments,
    )


def _openai_usage(usage: Any) -> TokenUsage:
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=_optional_int(_get_event_attr(usage, "input_tokens")),
        output_tokens=_optional_int(_get_event_attr(usage, "output_tokens")),
        total_tokens=_optional_int(_get_event_attr(usage, "total_tokens")),
    )


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _get_event_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
