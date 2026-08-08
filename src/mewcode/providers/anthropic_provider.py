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

ADAPTIVE_THINKING = {"type": "adaptive", "display": "omitted"}
MANUAL_THINKING = {"type": "enabled", "budget_tokens": 1024, "display": "omitted"}


class AnthropicProvider:
    def __init__(self, profile: ProviderProfile) -> None:
        self._profile = profile
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError("Anthropic SDK is not installed.") from exc

        self._client = anthropic.AsyncAnthropic(
            api_key=profile.api_key,
            base_url=profile.base_url,
        )

    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        return registry.to_anthropic_tools()

    async def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        request = self._build_request(messages, tools)
        if not self._profile.thinking:
            try:
                async for event in self._stream_request(request):
                    yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise self._to_provider_error(exc) from exc
            return

        adaptive_request = dict(request)
        adaptive_request["thinking"] = ADAPTIVE_THINKING
        try:
            async for event in self._stream_request(adaptive_request):
                yield event
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._is_adaptive_thinking_unsupported(exc):
                raise self._to_provider_error(exc) from exc

        manual_request = dict(request)
        manual_request["thinking"] = MANUAL_THINKING
        try:
            async for event in self._stream_request(manual_request):
                yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise self._to_provider_error(exc) from exc

    def assistant_messages(self, response: ModelResponse) -> list[ChatMessage]:
        content: list[dict[str, Any]] = []
        if response.text or not response.tool_calls:
            content.append({"type": "text", "text": response.text})
        content.extend(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.arguments,
            }
            for call in response.tool_calls
        )
        return [ChatMessage(role="assistant", content=content)]

    def tool_result_messages(
        self, executions: Sequence[ToolExecution]
    ) -> list[ChatMessage]:
        if not executions:
            return []
        return [
            ChatMessage(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": execution.request.id,
                        "content": _tool_result_payload(execution.result),
                        "is_error": not execution.result.ok,
                    }
                    for execution in executions
                ],
            )
        ]

    def _build_request(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._profile.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }
        if tools:
            request["tools"] = tools
        return request

    async def _stream_request(
        self, request: dict[str, Any]
    ) -> AsyncIterator[ProviderEvent]:
        async with self._client.messages.stream(**request) as stream:
            async for event in _parse_anthropic_events(stream):
                yield event

    def _is_adaptive_thinking_unsupported(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        message = str(exc).lower()
        return status_code == 400 and "adaptive thinking" in message and "not supported" in message

    def _to_provider_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            message = exc.message
        else:
            message = str(exc).strip() or exc.__class__.__name__
        message = message.replace(self._profile.api_key, "[redacted]")
        if message.startswith("Anthropic request failed:"):
            return ProviderError(message)
        return ProviderError(f"Anthropic request failed: {message}")


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


async def _parse_anthropic_events(events: Any) -> AsyncIterator[ProviderEvent]:
    calls: dict[int, dict[str, Any]] = {}
    input_tokens: int | None = None
    output_tokens: int | None = None

    async for event in events:
        event_type = _get_event_attr(event, "type")
        if event_type == "message_start":
            message = _get_event_attr(event, "message") or {}
            usage = _get_event_attr(message, "usage") or {}
            input_tokens = _optional_int(_get_event_attr(usage, "input_tokens"))
        elif event_type == "message_delta":
            usage = _get_event_attr(event, "usage") or {}
            value = _optional_int(_get_event_attr(usage, "output_tokens"))
            if value is not None:
                output_tokens = value
        elif event_type == "content_block_start":
            block = _get_event_attr(event, "content_block") or _get_event_attr(event, "block") or {}
            if _get_event_attr(block, "type") == "tool_use":
                index = _event_index(event)
                calls[index] = {
                    "id": _get_event_attr(block, "id") or "",
                    "name": _get_event_attr(block, "name") or "",
                    "parts": [],
                }
        elif event_type == "content_block_delta":
            delta = _get_event_attr(event, "delta") or {}
            delta_type = _get_event_attr(delta, "type")
            if delta_type == "text_delta":
                text = _get_event_attr(delta, "text") or ""
                if text:
                    yield ProviderTextDelta(text)
            elif delta_type == "input_json_delta":
                index = _event_index(event)
                call = calls.setdefault(index, {"id": "", "name": "", "parts": []})
                call["parts"].append(_get_event_attr(delta, "partial_json") or "")
        elif event_type == "content_block_stop":
            index = _event_index(event)
            call = calls.pop(index, None)
            if call is not None:
                yield ProviderToolCall(_build_tool_call(call))

    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    yield ProviderUsage(TokenUsage(input_tokens, output_tokens, total_tokens))


def _build_tool_call(call: dict[str, Any]) -> ToolCallRequest:
    raw_arguments = "".join(call["parts"])
    try:
        arguments = json.loads(raw_arguments) if raw_arguments else {}
        if not isinstance(arguments, dict):
            arguments = {}
    except json.JSONDecodeError:
        arguments = {}
    return ToolCallRequest(
        id=call["id"],
        name=call["name"],
        arguments=arguments,
        raw_arguments=raw_arguments,
    )


def _event_index(event: Any) -> int:
    value = _get_event_attr(event, "index")
    return value if isinstance(value, int) else 0


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _get_event_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
