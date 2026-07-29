from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .base import DEFAULT_MAX_TOKENS, ChatMessage, ProviderError, ProviderProfile


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

    def stream_reply(self, messages: list[ChatMessage]) -> Iterator[str]:
        request = {
            "model": self._profile.model,
            "input": self._build_input(messages),
            "max_output_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }

        try:
            stream = self._client.responses.create(**request)
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
                elif event_type == "error":
                    message = getattr(event, "message", None) or str(event)
                    raise ProviderError(f"OpenAI request failed: {message}")
        except Exception as exc:
            raise self._to_provider_error(exc) from exc

    def _build_input(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        return [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in messages
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
