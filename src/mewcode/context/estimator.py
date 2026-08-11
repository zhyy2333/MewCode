from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from mewcode.providers import ChatMessage, ModelRequest, TokenUsage

from .models import CharacterMeasure, RequestFootprint, TokenEstimate


def measure_text(text: str) -> CharacterMeasure:
    weighted = sum(1 if ord(character) < 128 else 4 for character in text)
    return CharacterMeasure(weighted)


def estimate_text_tokens(text: str) -> int:
    return measure_text(text).estimated_tokens


def take_prefix(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    remaining = token_budget * 4
    end = 0
    for end, character in enumerate(text, start=1):
        remaining -= 1 if ord(character) < 128 else 4
        if remaining < 0:
            return text[: end - 1]
    return text[:end]


def take_suffix(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    remaining = token_budget * 4
    start = len(text)
    for start in range(len(text) - 1, -1, -1):
        character = text[start]
        remaining -= 1 if ord(character) < 128 else 4
        if remaining < 0:
            return text[start + 1 :]
    return text[start:]


class TokenEstimator:
    def __init__(self) -> None:
        self._anchor_tokens: int | None = None
        self._anchor_footprint: RequestFootprint | None = None
        self._message_cache: dict[int, tuple[ChatMessage, CharacterMeasure, str]] = {}
        self._text_cache: dict[str, CharacterMeasure] = {}

    def estimate(self, request: ModelRequest) -> TokenEstimate:
        footprint = self.footprint(request)
        if self._anchor_tokens is None or self._anchor_footprint is None:
            return TokenEstimate(
                footprint.measure.estimated_tokens,
                False,
                footprint,
            )
        difference = (
            footprint.measure.weighted_characters
            - self._anchor_footprint.measure.weighted_characters
        )
        delta_tokens = math.ceil(difference / 4)
        return TokenEstimate(
            max(0, self._anchor_tokens + delta_tokens),
            True,
            footprint,
        )

    def footprint(self, request: ModelRequest) -> RequestFootprint:
        parts: list[tuple[CharacterMeasure, str]] = []
        parts.append(self._measure_cached(request.prompt.stable_system))
        parts.append(self._measure_cached(request.prompt.dynamic_system))
        for message in request.messages:
            parts.append(self._measure_message(message))
        tools_text = self._serialize_tools(request)
        parts.append(self._measure_cached(tools_text))
        measure = CharacterMeasure(
            sum(part.weighted_characters for part, _ in parts)
        )
        signature = hashlib.sha256(
            "\x00".join(signature for _, signature in parts).encode("utf-8")
        ).hexdigest()
        return RequestFootprint(measure, len(request.messages), signature)

    def observe(self, footprint: RequestFootprint, usage: TokenUsage) -> None:
        actual = usage.context_input_tokens
        if actual is None:
            actual = usage.input_tokens
        if actual is None or actual < 0:
            return
        self._anchor_tokens = actual
        self._anchor_footprint = footprint

    def estimate_message(self, message: ChatMessage) -> int:
        return self._measure_message(message)[0].estimated_tokens

    def _measure_message(self, message: ChatMessage) -> tuple[CharacterMeasure, str]:
        key = id(message)
        cached = self._message_cache.get(key)
        if cached is not None and cached[0] is message:
            return cached[1], cached[2]
        text = json.dumps(
            {
                "role": message.role,
                "content": message.content,
                "kind": message.kind.value if message.kind is not None else None,
                "group_id": message.group_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        measured = measure_text(text)
        signature = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self._message_cache[key] = (message, measured, signature)
        return measured, signature

    def _measure_cached(self, text: str) -> tuple[CharacterMeasure, str]:
        measured = self._text_cache.get(text)
        if measured is None:
            measured = measure_text(text)
            self._text_cache[text] = measured
        return measured, hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _serialize_tools(self, request: ModelRequest) -> str:
        if request.tools is None:
            return ""
        definitions: list[dict[str, Any]] = []
        for tool in sorted(request.tools.list(), key=lambda item: item.name):
            definitions.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                }
            )
        return json.dumps(
            definitions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
