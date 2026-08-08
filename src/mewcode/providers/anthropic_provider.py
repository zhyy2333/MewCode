from __future__ import annotations

from collections.abc import Iterator
from typing import Any
import json

from mewcode.tools import ToolCallRequest, ToolRegistry, ToolResult

from .base import (
    DEFAULT_MAX_TOKENS,
    ChatMessage,
    ProviderError,
    ProviderProfile,
    ProviderTextDelta,
    ProviderToolCall,
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

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=profile.api_key,
            base_url=profile.base_url,
        )

    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        return registry.to_anthropic_tools()

    def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ProviderTextDelta | ProviderToolCall]:
        request = self._build_request(messages, tools)
        if not self._profile.thinking:
            try:
                yield from self._stream_request(request)
            except Exception as exc:
                raise self._to_provider_error(exc) from exc
            return

        adaptive_request = dict(request)
        adaptive_request["thinking"] = ADAPTIVE_THINKING
        try:
            yield from self._stream_request(adaptive_request)
            return
        except Exception as exc:
            if not self._is_adaptive_thinking_unsupported(exc):
                raise self._to_provider_error(exc) from exc

        manual_request = dict(request)
        manual_request["thinking"] = MANUAL_THINKING
        try:
            yield from self._stream_request(manual_request)
        except Exception as exc:
            raise self._to_provider_error(exc) from exc

    def tool_result_message(
        self, tool_call: ToolCallRequest, result: ToolResult
    ) -> ChatMessage:
        return ChatMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": _tool_result_payload(result),
                    "is_error": not result.ok,
                }
            ],
        )

    def tool_call_message(self, tool_call: ToolCallRequest) -> ChatMessage:
        return ChatMessage(
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                }
            ],
        )

    def _build_request(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        request = {
            "model": self._profile.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }
        if tools:
            request["tools"] = tools
        return request

    def _stream_request(self, request: dict[str, Any]) -> Iterator[ProviderTextDelta | ProviderToolCall]:
        with self._client.messages.stream(**request) as stream:
            yield from _parse_anthropic_events(stream)

    def _is_adaptive_thinking_unsupported(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        message = str(exc).lower()
        return status_code == 400 and "adaptive thinking" in message and "not supported" in message

    def _to_provider_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        message = str(exc).strip() or exc.__class__.__name__
        message = message.replace(self._profile.api_key, "[redacted]")
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


def _parse_anthropic_events(events: Any) -> Iterator[ProviderTextDelta | ProviderToolCall]:
    tool_id = ""
    tool_name = ""
    input_parts: list[str] = []

    for event in events:
        event_type = _get_event_attr(event, "type")
        if event_type == "content_block_start":
            block = _get_event_attr(event, "content_block") or _get_event_attr(event, "block") or {}
            block_type = _get_event_attr(block, "type")
            if block_type == "tool_use":
                tool_id = _get_event_attr(block, "id") or ""
                tool_name = _get_event_attr(block, "name") or ""
                input_parts = []
        elif event_type == "content_block_delta":
            delta = _get_event_attr(event, "delta") or {}
            delta_type = _get_event_attr(delta, "type")
            if delta_type == "text_delta":
                text = _get_event_attr(delta, "text") or ""
                if text:
                    yield ProviderTextDelta(text)
            elif delta_type == "input_json_delta":
                input_parts.append(_get_event_attr(delta, "partial_json") or "")
        elif event_type == "content_block_stop" and tool_name:
            raw_arguments = "".join(input_parts)
            try:
                arguments = json.loads(raw_arguments) if raw_arguments else {}
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                arguments = {}
            yield ProviderToolCall(
                ToolCallRequest(
                    id=tool_id,
                    name=tool_name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                )
            )
            tool_id = ""
            tool_name = ""
            input_parts = []


def _get_event_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
