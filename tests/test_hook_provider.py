from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType

import pytest

from mewcode.hooks.models import (
    HookCatalog,
    HookEvent,
    HookRule,
    HookRuleKey,
    HookSource,
    PromptHookAction,
)
from mewcode.hooks.provider import HookedProvider
from mewcode.hooks.runtime import HookRuntime
from mewcode.prompting import PromptPackage
from mewcode.providers import ModelRequest, ProviderError, ProviderTextDelta
from fakes import ScriptedAsyncProvider, collect_async


class NoopExecutor:
    async def execute(self, rule, envelope, *, expects_decision):
        raise AssertionError("prompt rules do not call the external executor")

    async def close(self):
        return None


def _runtime(tmp_path: Path) -> HookRuntime:
    rules = (
        HookRule(HookRuleKey(HookSource.USER, Path("h"), 0), HookEvent.MESSAGE_BEFORE, None, PromptHookAction("injected")),
    )
    return HookRuntime(
        HookCatalog(rules, MappingProxyType({HookEvent.MESSAGE_BEFORE: rules})),
        NoopExecutor(),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )


def test_before_prompt_is_injected_into_current_request(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("ok")]])
    hooked = HookedProvider(provider, _runtime(tmp_path), "main")
    request = ModelRequest(PromptPackage("stable", "dynamic"), ())
    events = asyncio.run(collect_async(hooked.stream_reply(request)))
    assert events
    assert provider.calls[0].prompt.stable_system == "stable"
    assert "## Hook Context" in provider.calls[0].prompt.dynamic_system
    assert "injected" in provider.calls[0].prompt.dynamic_system
    assert request.prompt.dynamic_system == "dynamic"


def test_empty_runtime_passes_original_request_object(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([[]])
    hooked = HookedProvider(provider, HookRuntime.empty(tmp_path, "s"), "main")
    request = ModelRequest(PromptPackage("stable", "dynamic"), ())
    asyncio.run(collect_async(hooked.stream_reply(request)))
    assert provider.calls[0] is request


def test_provider_error_propagates(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([ProviderError("failed")])
    hooked = HookedProvider(provider, HookRuntime.empty(tmp_path, "s"), "main")
    with pytest.raises(ProviderError):
        asyncio.run(collect_async(hooked.stream_reply(ModelRequest(PromptPackage("", ""), ()))))


def test_delegate_message_conversion(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([[]])
    hooked = HookedProvider(provider, HookRuntime.empty(tmp_path, "s"), "main")
    delegated = hooked.tool_result_messages([], "g")
    assert delegated == provider.tool_result_messages([], "g")
