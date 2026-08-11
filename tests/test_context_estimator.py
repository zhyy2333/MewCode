from __future__ import annotations

import math

from mewcode.context import TokenEstimator, estimate_text_tokens
from mewcode.prompting import PromptPackage
from mewcode.providers import ChatMessage, ModelRequest, TokenUsage
from mewcode.tools import ToolRegistry

from tests.fakes import ControlledTool


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


def test_estimator_anchor_and_incremental_delta_use_actual_usage() -> None:
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


def test_footprint_covers_stable_dynamic_messages_and_sorted_tools() -> None:
    estimator = TokenEstimator()
    base = request(ChatMessage("user", "hello"))
    signatures = {estimator.footprint(base).signature}
    signatures.add(
        estimator.footprint(
            ModelRequest(PromptPackage("changed", "dynamic"), base.messages)
        ).signature
    )
    signatures.add(
        estimator.footprint(
            ModelRequest(PromptPackage("stable", "changed"), base.messages)
        ).signature
    )
    signatures.add(
        estimator.footprint(
            request(ChatMessage("user", "changed"))
        ).signature
    )
    registry = ToolRegistry([ControlledTool("z"), ControlledTool("a")])
    tool_request = ModelRequest(base.prompt, base.messages, registry)
    signatures.add(estimator.footprint(tool_request).signature)

    assert len(signatures) == 5
    reversed_registry = ToolRegistry([ControlledTool("a"), ControlledTool("z")])
    assert estimator.footprint(tool_request).signature == estimator.footprint(
        ModelRequest(base.prompt, base.messages, reversed_registry)
    ).signature


def test_missing_usage_keeps_estimate_unanchored_then_valid_usage_reanchors() -> None:
    estimator = TokenEstimator()
    model_request = request(ChatMessage("user", "hello"))
    footprint = estimator.footprint(model_request)

    estimator.observe(footprint, TokenUsage())
    assert estimator.estimate(model_request).anchored is False

    estimator.observe(footprint, TokenUsage(context_input_tokens=321))
    estimate = estimator.estimate(model_request)
    assert estimate.anchored is True
    assert estimate.input_tokens == 321
