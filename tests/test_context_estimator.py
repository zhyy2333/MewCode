from __future__ import annotations

import math

from mewcode.context import TokenEstimator, estimate_text_tokens
from mewcode.prompting import PromptPackage
from mewcode.providers import ChatMessage, ModelRequest, TokenUsage


def request(*messages: ChatMessage) -> ModelRequest:
    return ModelRequest(
        prompt=PromptPackage(stable_system="stable", dynamic_system="dynamic"),
        messages=messages,
    )


def test_weighted_character_estimate_is_conservative() -> None:
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("abcde") == 2
    assert estimate_text_tokens("猫") == 1
    assert estimate_text_tokens("猫a") == 2


def test_estimator_anchors_actual_usage_and_only_estimates_delta() -> None:
    estimator = TokenEstimator()
    before = request(ChatMessage("user", "hello"))
    before_estimate = estimator.estimate(before)

    estimator.observe(
        before_estimate.footprint,
        TokenUsage(input_tokens=80, context_input_tokens=100),
    )
    after = request(
        *before.messages,
        ChatMessage("assistant", "x" * 400),
    )
    after_estimate = estimator.estimate(after)
    expected_delta = math.ceil(
        (
            after_estimate.footprint.measure.weighted_characters
            - before_estimate.footprint.measure.weighted_characters
        )
        / 4
    )

    assert after_estimate.anchored is True
    assert after_estimate.input_tokens == 100 + expected_delta


def test_estimator_falls_back_to_input_usage() -> None:
    estimator = TokenEstimator()
    model_request = request(ChatMessage("user", "hello"))
    footprint = estimator.footprint(model_request)

    estimator.observe(footprint, TokenUsage(input_tokens=72))

    assert estimator.estimate(model_request).input_tokens == 72


def test_estimator_handles_history_replacement_after_anchor() -> None:
    estimator = TokenEstimator()
    long_request = request(ChatMessage("user", "x" * 4_000))
    footprint = estimator.footprint(long_request)
    estimator.observe(footprint, TokenUsage(context_input_tokens=1_500))

    compact_request = request(ChatMessage("assistant", "short summary"))
    estimate = estimator.estimate(compact_request)

    assert estimate.anchored is True
    assert 0 <= estimate.input_tokens < 1_500
