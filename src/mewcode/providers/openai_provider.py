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


class OpenAIProvider:
    def __init__(self, profile: ProviderProfile) -> None:
        self._profile = profile
        try:
            import openai
        except ImportError as exc:
            raise ProviderError("OpenAI SDK is not installed.") from exc

        self._client = openai.OpenAI(
            api_key=profile.api_key,
            base_url=profile.base_url,
        )

    def tool_definitions(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        return registry.to_openai_tools()

    def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ProviderTextDelta | ProviderToolCall]:
        request = {
            "model": self._profile.model,
            "input": self._build_input(messages),
            "max_output_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if tools:
            request["tools"] = tools

        try:
            stream = self._client.responses.create(**request)
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield ProviderTextDelta(delta)
                elif event_type == "error":
                    message = getattr(event, "message", None) or str(event)
                    raise ProviderError(f"OpenAI request failed: {message}")
                elif event_type in {
                    "response.output_item.added",
                    "response.function_call_arguments.delta",
                    "response.function_call_arguments.done",
                }:
                    yield from self._parse_tool_event(event)
        except Exception as exc:
            raise self._to_provider_error(exc) from exc

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

    def tool_result_message(
        self, tool_call: ToolCallRequest, result: ToolResult
    ) -> ChatMessage:
        return ChatMessage(
            role="tool",
            content={
                "type": "function_call_output",
                "call_id": tool_call.id,
                "output": _tool_result_payload(result),
            },
        )

    def tool_call_message(self, tool_call: ToolCallRequest) -> ChatMessage:
        return ChatMessage(
            role="assistant",
            content={
                "type": "function_call",
                "call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.raw_arguments,
            },
        )

    def _to_provider_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            message = exc.message
        else:
            message = str(exc).strip() or exc.__class__.__name__
        message = message.replace(self._profile.api_key, "[redacted]")
        if message.startswith("OpenAI request failed:"):
            return ProviderError(message)
        return ProviderError(f"OpenAI request failed: {message}")

    def _parse_tool_event(self, event: Any) -> Iterator[ProviderToolCall]:
        parser = getattr(self, "_tool_event_parser", None)
        if parser is None:
            parser = _OpenAIToolEventParser()
            self._tool_event_parser = parser
        yielded = parser.consume(event)
        if yielded is not None:
            yield yielded


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

    def consume(self, event: Any) -> ProviderToolCall | None:
        event_type = _get_event_attr(event, "type")
        if event_type == "response.output_item.added":
            item = _get_event_attr(event, "item") or {}
            item_type = _get_event_attr(item, "type")
            if item_type in {"function_call", "tool_call"}:
                call_id = _get_event_attr(item, "call_id") or _get_event_attr(item, "id") or ""
                name = _get_event_attr(item, "name") or ""
                self._calls[call_id] = {"name": name, "parts": []}
            return None

        call_id = _get_event_attr(event, "call_id") or _get_event_attr(event, "item_id") or ""
        if event_type == "response.function_call_arguments.delta":
            if call_id not in self._calls:
                self._calls[call_id] = {"name": "", "parts": []}
            self._calls[call_id]["parts"].append(_get_event_attr(event, "delta") or "")
            return None

        if event_type == "response.function_call_arguments.done":
            call = self._calls.pop(call_id, {"name": "", "parts": []})
            raw_arguments = _get_event_attr(event, "arguments")
            if raw_arguments is None:
                raw_arguments = "".join(call["parts"])
            try:
                arguments = json.loads(raw_arguments) if raw_arguments else {}
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                arguments = {}
            return ProviderToolCall(
                ToolCallRequest(
                    id=call_id,
                    name=call["name"],
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                )
            )
        return None


def _get_event_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
