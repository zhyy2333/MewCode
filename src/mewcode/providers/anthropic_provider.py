from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .base import DEFAULT_MAX_TOKENS, ChatMessage, ProviderError, ProviderProfile

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

    def stream_reply(self, messages: list[ChatMessage]) -> Iterator[str]:
        request = self._build_request(messages)
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

    def _build_request(self, messages: list[ChatMessage]) -> dict[str, Any]:
        return {
            "model": self._profile.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }

    def _stream_request(self, request: dict[str, Any]) -> Iterator[str]:
        with self._client.messages.stream(**request) as stream:
            for text in stream.text_stream:
                yield text

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
