from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any
from urllib.parse import urlparse

from mewcode.tools import (
    Tool,
    ToolCallRequest,
    ToolExecution,
    ToolRegistry,
    serialize_tool_result,
)

from .base import (
    ChatMessage,
    MessageKind,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderEvent,
    ProviderFinished,
    ProviderFinishReason,
    ProviderInternalPart,
    ProviderProfile,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    TokenUsage,
    ThinkingMode,
)

ADAPTIVE_THINKING = {"type": "adaptive", "display": "omitted"}
MANUAL_THINKING = {"type": "enabled", "budget_tokens": 1024, "display": "omitted"}
DISABLED_THINKING = {"type": "disabled"}


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

    async def stream_reply(
        self,
        model_request: ModelRequest,
    ) -> AsyncIterator[ProviderEvent]:
        request = self._build_request(model_request)
        if self._profile.thinking is ThinkingMode.AUTO:
            try:
                async for event in self._stream_request(request):
                    yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise self._to_provider_error(exc) from exc
            return

        if self._profile.thinking is ThinkingMode.DISABLED:
            disabled_request = dict(request)
            disabled_request["thinking"] = DISABLED_THINKING
            try:
                async for event in self._stream_request(disabled_request):
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

    def assistant_messages(
        self, response: ModelResponse, group_id: str | None = None
    ) -> list[ChatMessage]:
        content: list[dict[str, Any]] = [
            part.data for part in response.internal_parts
        ]
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
        return [
            ChatMessage(
                role="assistant",
                content=content,
                kind=(
                    MessageKind.TOOL_CALL
                    if response.tool_calls
                    else MessageKind.ASSISTANT
                ),
                group_id=group_id,
            )
        ]

    def tool_result_messages(
        self,
        executions: Sequence[ToolExecution],
        group_id: str | None = None,
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
                        "content": serialize_tool_result(execution.result),
                        "is_error": not execution.result.ok,
                    }
                    for execution in executions
                ],
                kind=MessageKind.TOOL_RESULT,
                group_id=group_id,
            )
        ]

    def _build_request(
        self,
        model_request: ModelRequest,
    ) -> dict[str, Any]:
        context_system = [
            str(message.content)
            for message in model_request.messages
            if message.kind in {MessageKind.SUMMARY, MessageKind.BOUNDARY}
        ]
        dialogue_messages = [
            message
            for message in model_request.messages
            if message.kind not in {MessageKind.SUMMARY, MessageKind.BOUNDARY}
        ]
        request: dict[str, Any] = {
            "model": self._profile.model,
            "max_tokens": model_request.max_output_tokens,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in dialogue_messages
            ],
        }
        stable_system = model_request.prompt.stable_system
        dynamic_system = model_request.prompt.dynamic_system
        if _is_official_anthropic_host(self._profile.base_url):
            system: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": stable_system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            if dynamic_system:
                system.append({"type": "text", "text": dynamic_system})
            system.extend(
                {"type": "text", "text": content}
                for content in context_system
            )
            request["system"] = system
        else:
            request["system"] = _join_system(
                stable_system,
                "\n\n".join(
                    part
                    for part in [dynamic_system, *context_system]
                    if part
                ),
            )
        if model_request.tools is not None:
            tools = _anthropic_tools(model_request.tools)
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


def _anthropic_tools(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [_anthropic_tool(tool) for tool in sorted(registry.list(), key=lambda item: item.name)]


def _anthropic_tool(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters_schema,
    }


def _is_official_anthropic_host(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "").casefold() == "api.anthropic.com"


def _join_system(stable_system: str, dynamic_system: str) -> str:
    if not dynamic_system:
        return stable_system
    return f"{stable_system}\n\n{dynamic_system}"


async def _parse_anthropic_events(events: Any) -> AsyncIterator[ProviderEvent]:
    calls: dict[int, dict[str, Any]] = {}
    internal_blocks: dict[int, dict[str, Any]] = {}
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    finish_reason: ProviderFinishReason | None = None
    emitted_tool_call = False

    async for event in events:
        event_type = _get_event_attr(event, "type")
        if event_type == "message_start":
            message = _get_event_attr(event, "message") or {}
            usage = _get_event_attr(message, "usage") or {}
            input_tokens = _optional_int(_get_event_attr(usage, "input_tokens"))
            cache_read_tokens = _optional_int(
                _get_event_attr(usage, "cache_read_input_tokens")
            )
            cache_write_tokens = _optional_int(
                _get_event_attr(usage, "cache_creation_input_tokens")
            )
        elif event_type == "message_delta":
            delta = _get_event_attr(event, "delta") or {}
            stop_reason = _get_event_attr(delta, "stop_reason") or _get_event_attr(
                event, "stop_reason"
            )
            if stop_reason is not None:
                finish_reason = _anthropic_finish_reason(stop_reason)
            usage = _get_event_attr(event, "usage") or {}
            value = _optional_int(_get_event_attr(usage, "output_tokens"))
            if value is not None:
                output_tokens = value
        elif event_type == "content_block_start":
            block = _get_event_attr(event, "content_block") or _get_event_attr(event, "block") or {}
            block_type = _get_event_attr(block, "type")
            if block_type == "tool_use":
                index = _event_index(event)
                calls[index] = {
                    "id": _get_event_attr(block, "id") or "",
                    "name": _get_event_attr(block, "name") or "",
                    "parts": [],
                }
            elif block_type in {"thinking", "redacted_thinking"}:
                internal_blocks[_event_index(event)] = _anthropic_internal_block(block)
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
            elif delta_type == "thinking_delta":
                block = internal_blocks.setdefault(
                    _event_index(event), {"type": "thinking", "thinking": ""}
                )
                block["thinking"] = block.get("thinking", "") + (
                    _get_event_attr(delta, "thinking") or ""
                )
            elif delta_type == "signature_delta":
                block = internal_blocks.setdefault(
                    _event_index(event), {"type": "thinking", "thinking": ""}
                )
                block["signature"] = block.get("signature", "") + (
                    _get_event_attr(delta, "signature") or ""
                )
        elif event_type == "content_block_stop":
            index = _event_index(event)
            call = calls.pop(index, None)
            if call is not None:
                emitted_tool_call = True
                yield ProviderToolCall(_build_tool_call(call))
            internal = internal_blocks.pop(index, None)
            if internal is not None:
                yield ProviderInternalPart(internal)

    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    yield ProviderUsage(
        TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            context_input_tokens=_sum_optional(
                input_tokens, cache_read_tokens, cache_write_tokens
            ),
        )
    )
    if finish_reason is None:
        finish_reason = (
            ProviderFinishReason.TOOL_CALLS
            if emitted_tool_call
            else ProviderFinishReason.NATURAL
        )
    yield ProviderFinished(finish_reason)


def _anthropic_finish_reason(value: Any) -> ProviderFinishReason:
    if value in {"end_turn", "stop_sequence"}:
        return ProviderFinishReason.NATURAL
    if value == "tool_use":
        return ProviderFinishReason.TOOL_CALLS
    if value in {"max_tokens", "model_context_window_exceeded"}:
        return ProviderFinishReason.OUTPUT_LIMIT
    raise ProviderError(f"Anthropic request failed: unsupported stop reason '{value}'.")


def _anthropic_internal_block(block: Any) -> dict[str, Any]:
    block_type = _get_event_attr(block, "type")
    if block_type == "redacted_thinking":
        return {
            "type": "redacted_thinking",
            "data": _get_event_attr(block, "data") or "",
        }
    result: dict[str, Any] = {
        "type": "thinking",
        "thinking": _get_event_attr(block, "thinking") or "",
    }
    signature = _get_event_attr(block, "signature")
    if signature:
        result["signature"] = signature
    return result


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


def _sum_optional(*values: int | None) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _get_event_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
